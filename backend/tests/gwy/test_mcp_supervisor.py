from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.config import settings
from app.gwy.services import mcp_supervisor


@dataclass
class FakeProcess:
    command: list[str]
    env: dict[str, str]
    returncode: int | None = None

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        self.returncode = 0
        return 0

    def terminate(self) -> None:
        self.returncode = 0

    def kill(self) -> None:
        self.returncode = -9


def test_supervisor_starts_local_mcp_processes_by_default(monkeypatch) -> None:
    monkeypatch.setattr(settings, "WEB_MCP_URL", None)
    monkeypatch.setattr(settings, "DB_MCP_URL", None)
    monkeypatch.setattr(settings, "PLAYWRIGHT_MCP_URL", None)

    commands: list[list[str]] = []
    envs: list[dict[str, str]] = []

    def fake_popen(command: list[str], **kwargs: Any) -> FakeProcess:
        commands.append(command)
        env = dict(kwargs.get("env") or {})
        envs.append(env)
        return FakeProcess(command=command, env=env)

    supervisor = mcp_supervisor.MCPProcessSupervisor(
        backend_command=["python", "-m", "uvicorn", "app.main:app"],
        startup_timeout_seconds=1.0,
    )
    monkeypatch.setattr(mcp_supervisor.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(supervisor, "_is_http_ready", lambda url: True)
    monkeypatch.setattr(supervisor, "_install_signal_handlers", lambda: {})
    monkeypatch.setattr(supervisor, "_restore_signal_handlers", lambda previous: None)
    monkeypatch.setattr(supervisor, "_terminate_managed_processes", lambda processes: None)
    monkeypatch.setattr(supervisor, "_terminate_process", lambda process: None)

    exit_code = supervisor.run()

    assert exit_code == 0
    assert any("web_server" in " ".join(command) for command in commands)
    assert any("db_server" in " ".join(command) for command in commands)
    assert any("playwright_server" in " ".join(command) for command in commands)
    backend_env = envs[-1]
    assert backend_env["WEB_MCP_URL"] == "http://127.0.0.1:8001/mcp"
    assert backend_env["DB_MCP_URL"] == "http://127.0.0.1:8002/mcp"
    assert backend_env["PLAYWRIGHT_MCP_URL"] == "http://127.0.0.1:8931/mcp"


def test_supervisor_skips_local_mcp_when_external_urls_are_configured(monkeypatch) -> None:
    monkeypatch.setattr(settings, "WEB_MCP_URL", "http://web-mcp:8001/mcp")
    monkeypatch.setattr(settings, "DB_MCP_URL", "http://db-mcp:8002/mcp")
    monkeypatch.setattr(settings, "PLAYWRIGHT_MCP_URL", "http://playwright-mcp:8931/mcp")

    commands: list[list[str]] = []
    envs: list[dict[str, str]] = []

    def fake_popen(command: list[str], **kwargs: Any) -> FakeProcess:
        commands.append(command)
        env = dict(kwargs.get("env") or {})
        envs.append(env)
        return FakeProcess(command=command, env=env)

    supervisor = mcp_supervisor.MCPProcessSupervisor(
        backend_command=["python", "-m", "uvicorn", "app.main:app"],
        startup_timeout_seconds=1.0,
    )
    monkeypatch.setattr(mcp_supervisor.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(supervisor, "_is_http_ready", lambda url: True)
    monkeypatch.setattr(supervisor, "_install_signal_handlers", lambda: {})
    monkeypatch.setattr(supervisor, "_restore_signal_handlers", lambda previous: None)
    monkeypatch.setattr(supervisor, "_terminate_managed_processes", lambda processes: None)
    monkeypatch.setattr(supervisor, "_terminate_process", lambda process: None)

    exit_code = supervisor.run()

    assert exit_code == 0
    assert len(commands) == 1
    assert commands[0] == ["python", "-m", "uvicorn", "app.main:app"]
    backend_env = envs[0]
    assert backend_env["WEB_MCP_URL"] == "http://web-mcp:8001/mcp"
    assert backend_env["DB_MCP_URL"] == "http://db-mcp:8002/mcp"
    assert backend_env["PLAYWRIGHT_MCP_URL"] == "http://playwright-mcp:8931/mcp"
