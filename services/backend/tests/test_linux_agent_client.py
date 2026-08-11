import httpx
import pytest
from types import SimpleNamespace

import app.linux_agent_client as linux_agent_client
from app.linux_agent_client import (
    LinuxAgentIntegrationError,
    fetch_linux_account_inventory,
)


def test_fetch_linux_account_inventory(monkeypatch) -> None:
    monkeypatch.setattr(
        linux_agent_client,
        "settings",
        SimpleNamespace(
            linux_agent_token="test-token-with-at-least-32-characters",
            linux_agent_connect_timeout_seconds=1,
            linux_agent_read_timeout_seconds=1,
            linux_agent_tls_verify=True,
        ),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"].startswith("Bearer ")
        return httpx.Response(
            200,
            json={
                "hostname": "host-01",
                "collected_at": "2026-08-10T00:00:00Z",
                "discovered_count": 3,
                "total_count": 2,
                "human_count": 2,
                "login_enabled_count": 1,
                "users": [
                    {
                        "username": "developer",
                        "uid": 1000,
                        "gid": 1000,
                        "comment": "Developer",
                        "home": "/home/developer",
                        "shell": "/bin/bash",
                        "login_enabled": True,
                    }
                ],
            },
        )

    result = fetch_linux_account_inventory(
        "https://agent.example.internal:39110",
        transport=httpx.MockTransport(handler),
    )
    assert result["total_count"] == 2
    assert result["users"][0]["username"] == "developer"


def test_rejects_invalid_agent_payload(monkeypatch) -> None:
    monkeypatch.setattr(
        linux_agent_client,
        "settings",
        SimpleNamespace(
            linux_agent_token="test-token-with-at-least-32-characters",
            linux_agent_connect_timeout_seconds=1,
            linux_agent_read_timeout_seconds=1,
            linux_agent_tls_verify=True,
        ),
    )
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"users": []}))
    with pytest.raises(LinuxAgentIntegrationError, match="账号统计无效"):
        fetch_linux_account_inventory(
            "https://agent.example.internal:39110",
            transport=transport,
        )
