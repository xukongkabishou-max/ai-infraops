import json
from functools import lru_cache

import redis

from .config import settings
from .db import execute_query


@lru_cache(maxsize=1)
def get_redis_client() -> redis.Redis:
    return redis.Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        password=settings.redis_password or None,
        db=settings.redis_db,
        ssl=settings.redis_tls,
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=5,
    )


def session_key(client_type: str, token: str) -> str:
    return f"infraops:session:{client_type}:{token}"


def save_session(client_type: str, token: str, payload: dict) -> None:
    client = get_redis_client()
    client.setex(
        session_key(client_type, token),
        settings.session_ttl_seconds,
        json.dumps(payload, ensure_ascii=False),
    )


def load_session(client_type: str, token: str) -> dict | None:
    client = get_redis_client()
    raw_payload = client.get(session_key(client_type, token))
    if not raw_payload:
        return None
    payload = json.loads(raw_payload)
    users = execute_query("SELECT auth_version,is_active,is_superuser FROM rbac_users WHERE id=%s",
                          (payload.get("user", {}).get("id"),))
    if not users or not users[0]["is_active"] or payload.get("_auth_version", 0) != users[0]["auth_version"]:
        client.delete(session_key(client_type, token))
        return None
    payload["user"]["isSuperuser"] = bool(users[0]["is_superuser"])
    client.expire(session_key(client_type, token), settings.session_ttl_seconds)
    return payload


def delete_session(client_type: str, token: str) -> None:
    client = get_redis_client()
    client.delete(session_key(client_type, token))
