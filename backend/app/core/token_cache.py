from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlmodel import Session

from app.core.config import settings
from app.models import User


def store_access_token_session(token: str, user: User) -> None:
    client = _build_redis_client()
    if client is None:
        return

    payload = {
        "id": str(user.id),
        "email": user.email,
        "is_active": user.is_active,
        "is_superuser": user.is_superuser,
        "full_name": user.full_name,
        "hashed_password": user.hashed_password,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }
    ttl_seconds = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    client.setex(_token_key(token), ttl_seconds, json.dumps(payload, ensure_ascii=False))


def load_access_token_session(token: str) -> dict[str, Any] | None:
    client = _build_redis_client()
    if client is None:
        return None

    raw = client.get(_token_key(token))
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def restore_user_from_token(
    *,
    session: Session,
    token: str,
    user_id: str,
) -> User | None:
    cached = load_access_token_session(token)
    if not cached or str(cached.get("id") or "") != str(user_id):
        return None

    user = User(
        id=cached["id"],
        email=cached["email"],
        is_active=bool(cached.get("is_active", True)),
        is_superuser=bool(cached.get("is_superuser", False)),
        full_name=cached.get("full_name"),
        hashed_password=str(cached.get("hashed_password") or ""),
        created_at=_parse_datetime(cached.get("created_at")),
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def invalidate_access_token(token: str) -> None:
    client = _build_redis_client()
    if client is None:
        return
    client.delete(_token_key(token))


def _build_redis_client() -> Any | None:
    if not settings.REDIS_URL:
        return None
    try:
        import redis

        client = redis.Redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
        )
        client.ping()
        return client
    except Exception:  # pragma: no cover - Redis best-effort
        return None


def _token_key(token: str) -> str:
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return f"gwy:auth:token:{token_hash}"


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed
