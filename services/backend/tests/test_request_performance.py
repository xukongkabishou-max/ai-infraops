import asyncio
import threading
from unittest.mock import Mock

import httpx
from fastapi import FastAPI, Request

from app import audit
from app import session_store
from app.logging_config import RequestLoggingMiddleware, request_id_context
from app.request_metrics import add_metric, measure


def test_audit_is_awaited_without_blocking_event_loop_and_shares_request_id(monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    records = []

    def slow_audit(request, **kwargs):
        with measure("audit_ms"):
            entered.set()
            assert release.wait(3)
            records.append((request_id_context.get(), kwargs["status_code"]))

    monkeypatch.setattr(audit, "record_audit_event", slow_audit)
    app = FastAPI()
    app.add_middleware(audit.SecurityAuditMiddleware)
    app.add_middleware(RequestLoggingMiddleware)

    @app.get("/protected")
    def protected(request: Request):
        audit.attach_audit_session(request, {"user":{"id":1}}, "user_web")
        add_metric("db_queries", 2)
        add_metric("db_sql_ms", 12)
        return {"ok":True}

    @app.get("/heartbeat")
    async def heartbeat(): return {"ok":True}

    async def verify():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
            pending = asyncio.create_task(client.get("/protected", headers={"X-Request-ID":"timing-test"}))
            try:
                assert await asyncio.to_thread(entered.wait, 2)
                probe = await asyncio.wait_for(client.get("/heartbeat"), timeout=0.5)
                assert probe.status_code == 200
                assert not pending.done()
            finally: release.set()
            response = await pending
            assert response.headers["x-request-id"] == "timing-test"
            assert "db_sql;dur=12" in response.headers["server-timing"]
            assert '2 queries' in response.headers['server-timing']
            assert float(response.headers['x-response-time-ms']) >= 0
    asyncio.run(verify())
    assert records == [("timing-test",200)]


def test_session_refresh_uses_one_redis_round_trip_and_supports_older_servers(monkeypatch):
    client = Mock()
    payload = '{"user":{"id":1},"_auth_version":0}'
    client.getex.return_value = payload
    client.get.return_value = payload
    monkeypatch.setattr(session_store, "_getex_supported", True)
    monkeypatch.setattr(session_store, "get_redis_client", lambda: client)
    monkeypatch.setattr(session_store, "execute_query", lambda *args: [{"auth_version":0,"is_active":1,"is_superuser":0}])
    assert session_store.load_session("user_web", "token")
    client.getex.assert_called_once()
    client.get.assert_not_called()
    client.expire.assert_not_called()
    client.reset_mock()
    client.getex.side_effect = session_store.redis.ResponseError("unknown command 'GETEX'")
    assert session_store.load_session("user_web", "token")
    client.get.assert_called_once()
    client.expire.assert_called_once()
    client.reset_mock()
    assert session_store.load_session("user_web", "token")
    client.getex.assert_not_called()
