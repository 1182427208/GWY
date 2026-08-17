from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

from app.core.config import settings


@dataclass(slots=True)
class ManagedProcess:
    name: str
    process: subprocess.Popen[Any]
    url: str | None = None


class MCPProcessSupervisor:
    def __init__(
        self,
        *,
        backend_command: list[str] | None = None,
        startup_timeout_seconds: float = 45.0,
        healthcheck_interval_seconds: float = 0.5,
    ) -> None:
        self.backend_command = backend_command or [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "0.0.0.0",
            "--port",
            "8000",
            "--workers",
            "4",
        ]
        self.startup_timeout_seconds = startup_timeout_seconds
        self.healthcheck_interval_seconds = healthcheck_interval_seconds
        self.project_root = Path(__file__).resolve().parents[3]
        self.backend_root = self.project_root / "backend"

    def run(self) -> int:
        managed: list[ManagedProcess] = []
        backend_process: subprocess.Popen[Any] | None = None
        previous_handlers = self._install_signal_handlers()
        try:
            managed.extend(self._start_local_mcp_processes())
            self._wait_for_local_mcp(managed)
            backend_env = self._build_backend_env(managed)
            backend_process = subprocess.Popen(
                self.backend_command,
                cwd=str(self.backend_root),
                env=backend_env,
            )
            return backend_process.wait()
        finally:
            self._restore_signal_handlers(previous_handlers)
            self._terminate_process(backend_process)
            self._terminate_managed_processes(managed)

    def _start_local_mcp_processes(self) -> list[ManagedProcess]:
        processes: list[ManagedProcess] = []
        for spec in self._mcp_specs():
            if self._should_use_external_url(spec["env_var"]):
                continue
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    spec["module"],
                ],
                cwd=str(self.backend_root),
                env=os.environ.copy(),
            )
            processes.append(
                ManagedProcess(
                    name=spec["name"],
                    process=process,
                    url=spec["url"],
                )
            )
        return processes

    def _wait_for_local_mcp(self, processes: list[ManagedProcess]) -> None:
        deadline = time.monotonic() + self.startup_timeout_seconds
        pending = [item for item in processes if item.url]
        while pending and time.monotonic() < deadline:
            still_pending: list[ManagedProcess] = []
            for item in pending:
                if item.process.poll() is not None:
                    raise RuntimeError(
                        f"{item.name} MCP exited during startup with code {item.process.returncode}"
                    )
                if self._is_http_ready(item.url or ""):
                    continue
                still_pending.append(item)
            pending = still_pending
            if pending:
                time.sleep(self.healthcheck_interval_seconds)
        if pending:
            names = ", ".join(item.name for item in pending)
            raise TimeoutError(f"Timed out waiting for MCP servers: {names}")

    def _build_backend_env(self, processes: list[ManagedProcess]) -> dict[str, str]:
        env = os.environ.copy()
        for item in processes:
            if item.url:
                env[self._env_var_name(item.name)] = item.url
        for spec in self._mcp_specs():
            current = str(
                env.get(spec["env_var"])
                or getattr(settings, spec["env_var"], "")
                or ""
            ).strip()
            if current:
                env[spec["env_var"]] = current
            else:
                env[spec["env_var"]] = spec["url"]
        return env

    def _terminate_managed_processes(self, processes: list[ManagedProcess]) -> None:
        for item in reversed(processes):
            self._terminate_process(item.process)

    def _terminate_process(self, process: subprocess.Popen[Any] | None) -> None:
        if process is None or process.poll() is not None:
            return
        try:
            process.terminate()
            process.wait(timeout=10)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass

    def _install_signal_handlers(self) -> dict[int, Any]:
        previous = {
            signal.SIGINT: signal.getsignal(signal.SIGINT),
            signal.SIGTERM: signal.getsignal(signal.SIGTERM),
        }

        def _handler(signum: int, _frame: Any) -> None:
            raise KeyboardInterrupt(f"received signal {signum}")

        signal.signal(signal.SIGINT, _handler)
        signal.signal(signal.SIGTERM, _handler)
        return previous

    def _restore_signal_handlers(self, previous: dict[int, Any]) -> None:
        for signum, handler in previous.items():
            signal.signal(signum, handler)

    def _is_http_ready(self, url: str) -> bool:
        try:
            with urlopen(url, timeout=1) as response:
                return response.status in {200, 202, 404, 405}
        except URLError:
            return False
        except Exception:
            return False

    def _should_use_external_url(self, env_var: str) -> bool:
        value = str(os.environ.get(env_var) or getattr(settings, env_var, "") or "").strip()
        return bool(value)

    def _mcp_specs(self) -> list[dict[str, str]]:
        return [
            {
                "name": "web",
                "module": "app.gwy.mcp_tools.web_server",
                "env_var": "WEB_MCP_URL",
                "url": "http://127.0.0.1:8001/mcp",
            },
            {
                "name": "db",
                "module": "app.gwy.mcp_tools.db_server",
                "env_var": "DB_MCP_URL",
                "url": "http://127.0.0.1:8002/mcp",
            },
            {
                "name": "playwright",
                "module": "app.gwy.mcp_tools.playwright_server",
                "env_var": "PLAYWRIGHT_MCP_URL",
                "url": "http://127.0.0.1:8931/mcp",
            },
        ]

    def _env_var_name(self, name: str) -> str:
        for spec in self._mcp_specs():
            if spec["name"] == name:
                return spec["env_var"]
        raise KeyError(name)


def main() -> int:
    supervisor = MCPProcessSupervisor()
    return supervisor.run()


if __name__ == "__main__":
    raise SystemExit(main())
