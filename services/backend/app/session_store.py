import json

import redis

from .config import settings


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
    client.expire(session_key(client_type, token), settings.session_ttl_seconds)
    return json.loads(raw_payload)


def delete_session(client_type: str, token: str) -> None:
    client = get_redis_client()
    client.delete(session_key(client_type, token))
