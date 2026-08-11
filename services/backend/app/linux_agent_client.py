from __future__ import annotations

from typing import Any

import httpx

from .config import settings


class LinuxAgentIntegrationError(RuntimeError):
    pass


def fetch_linux_account_inventory(
    agent_url: str,
    *,
    transport: httpx.BaseTransport | None = None,
) -> dict[str, Any]:
    if not settings.linux_agent_token:
        raise LinuxAgentIntegrationError("后端尚未配置 Linux Agent Token")

    timeout = httpx.Timeout(
        connect=settings.linux_agent_connect_timeout_seconds,
        read=settings.linux_agent_read_timeout_seconds,
        write=settings.linux_agent_read_timeout_seconds,
        pool=settings.linux_agent_connect_timeout_seconds,
    )
    try:
        with httpx.Client(
            timeout=timeout,
            verify=settings.linux_agent_tls_verify,
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        ) as client:
            response = client.get(
                f"{agent_url.rstrip('/')}/v1/users",
                headers={"Authorization": f"Bearer {settings.linux_agent_token}"},
            )
    except httpx.ConnectTimeout as exc:
        raise LinuxAgentIntegrationError("连接 Linux Agent 超时") from exc
    except httpx.ReadTimeout as exc:
        raise LinuxAgentIntegrationError("Linux Agent 响应超时") from exc
    except httpx.ConnectError as exc:
        raise LinuxAgentIntegrationError("无法连接 Linux Agent") from exc
    except httpx.HTTPError as exc:
        raise LinuxAgentIntegrationError(f"Linux Agent 请求失败：{exc}") from exc

    if response.status_code == 401:
        raise LinuxAgentIntegrationError("Linux Agent Token 校验失败")
    if response.status_code != 200:
        raise LinuxAgentIntegrationError(
            f"Linux Agent 返回异常状态：HTTP {response.status_code}"
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise LinuxAgentIntegrationError("Linux Agent 返回了无效 JSON") from exc
    _validate_inventory(payload)
    return payload


def _validate_inventory(payload: object) -> None:
    if not isinstance(payload, dict):
        raise LinuxAgentIntegrationError("Linux Agent 返回结构无效")
    required_counts = (
        "discovered_count",
        "total_count",
        "human_count",
        "login_enabled_count",
    )
    if any(not isinstance(payload.get(field), int) for field in required_counts):
        raise LinuxAgentIntegrationError("Linux Agent 返回的账号统计无效")
    users = payload.get("users")
    if not isinstance(users, list):
        raise LinuxAgentIntegrationError("Linux Agent 返回的账号列表无效")
    for user in users:
        if not isinstance(user, dict) or not isinstance(user.get("username"), str):
            raise LinuxAgentIntegrationError("Linux Agent 返回的账号记录无效")
