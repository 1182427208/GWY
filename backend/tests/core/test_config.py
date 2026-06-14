from __future__ import annotations

from app.core.config import settings


def test_all_cors_origins_include_localhost_variants() -> None:
    origins = settings.all_cors_origins

    assert "http://localhost" in origins
    assert "http://localhost:5173" in origins
    assert "http://127.0.0.1" in origins
    assert "http://127.0.0.1:5173" in origins
