import httpx


class MonitoringPlatformProbeError(RuntimeError):
    pass


def probe_monitoring_platform(
    url: str,
    transport: httpx.BaseTransport | None = None,
) -> None:
    timeout = httpx.Timeout(connect=5, read=8, write=5, pool=5)
    try:
        with httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            trust_env=False,
            transport=transport,
        ) as client:
            response = client.get(url)
            response.raise_for_status()
    except httpx.ConnectTimeout as exc:
        raise MonitoringPlatformProbeError("连接监控平台超时") from exc
    except httpx.ReadTimeout as exc:
        raise MonitoringPlatformProbeError("读取监控平台响应超时") from exc
    except httpx.ConnectError as exc:
        raise MonitoringPlatformProbeError("无法连接监控平台") from exc
    except httpx.HTTPStatusError as exc:
        raise MonitoringPlatformProbeError(
            f"监控平台返回 HTTP {exc.response.status_code}"
        ) from exc
    except httpx.HTTPError as exc:
        raise MonitoringPlatformProbeError("监控平台请求失败") from exc
