from pathlib import PurePosixPath
from urllib.parse import urlsplit, urlunsplit

import httpx

from .config import settings


class NacosIntegrationError(RuntimeError):
    pass


class _NacosPathUnavailable(RuntimeError):
    pass


def fetch_nacos_catalog(
    base_url: str, username: str, password: str
) -> list[dict]:
    timeout = httpx.Timeout(
        connect=settings.nacos_connect_timeout_seconds,
        read=settings.nacos_read_timeout_seconds,
        write=settings.nacos_read_timeout_seconds,
        pool=settings.nacos_connect_timeout_seconds,
    )
    last_path_error: Exception | None = None
    with httpx.Client(timeout=timeout, follow_redirects=False, trust_env=False) as client:
        for api_base_url in _candidate_api_base_urls(base_url):
            try:
                return _fetch_v2_catalog(client, api_base_url, username, password)
            except _NacosPathUnavailable as exc:
                last_path_error = exc
                continue
            except httpx.ConnectTimeout as exc:
                raise NacosIntegrationError("连接 Nacos 超时") from exc
            except httpx.ReadTimeout as exc:
                raise NacosIntegrationError("等待 Nacos 响应超时") from exc
            except httpx.ConnectError as exc:
                raise NacosIntegrationError("无法连接 Nacos，请检查地址、端口和网络") from exc
            except httpx.HTTPError as exc:
                raise NacosIntegrationError("Nacos HTTP 请求失败") from exc
    raise NacosIntegrationError("该 Nacos 暂不支持元数据目录接口") from last_path_error


def fetch_nacos_config_content(
    base_url: str,
    username: str,
    password: str,
    namespace_id: str,
    group: str,
    data_id: str,
) -> str:
    timeout = httpx.Timeout(
        connect=settings.nacos_connect_timeout_seconds,
        read=settings.nacos_read_timeout_seconds,
        write=settings.nacos_read_timeout_seconds,
        pool=settings.nacos_connect_timeout_seconds,
    )
    last_path_error: Exception | None = None
    with httpx.Client(timeout=timeout, follow_redirects=False, trust_env=False) as client:
        for api_base_url in _candidate_api_base_urls(base_url):
            try:
                return _fetch_v2_config_content(
                    client,
                    api_base_url,
                    username,
                    password,
                    namespace_id,
                    group,
                    data_id,
                )
            except _NacosPathUnavailable as exc:
                last_path_error = exc
                continue
            except httpx.ConnectTimeout as exc:
                raise NacosIntegrationError("连接 Nacos 超时") from exc
            except httpx.ReadTimeout as exc:
                raise NacosIntegrationError("等待 Nacos 响应超时") from exc
            except httpx.ConnectError as exc:
                raise NacosIntegrationError(
                    "无法连接 Nacos，请检查地址、端口和网络"
                ) from exc
            except httpx.HTTPError as exc:
                raise NacosIntegrationError("Nacos HTTP 请求失败") from exc
    raise NacosIntegrationError("该 Nacos 暂不支持配置读取接口") from last_path_error


def _fetch_v2_config_content(
    client: httpx.Client,
    api_base_url: str,
    username: str,
    password: str,
    namespace_id: str,
    group: str,
    data_id: str,
) -> str:
    config_path = f"{api_base_url}/v2/cs/config"
    params = {
        "namespaceId": "" if namespace_id == "public" else namespace_id,
        "group": group,
        "dataId": data_id,
    }
    response = client.get(config_path, params=params)
    if response.status_code in {401, 403}:
        params["accessToken"] = _login_v2(client, api_base_url, username, password)
        response = client.get(config_path, params=params)
    return _read_config_content(response)


def _read_config_content(response: httpx.Response) -> str:
    if response.status_code == 404:
        raise _NacosPathUnavailable()
    if response.status_code in {401, 403}:
        raise NacosIntegrationError("Nacos 凭证无权读取该配置")
    if response.status_code >= 400:
        raise NacosIntegrationError(f"Nacos API 返回 HTTP {response.status_code}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise NacosIntegrationError("Nacos 配置接口响应格式无效") from exc
    if not isinstance(payload, dict):
        raise NacosIntegrationError("Nacos 配置接口响应格式无效")
    code = payload.get("code")
    if code not in {None, 0, 200}:
        raise NacosIntegrationError("Nacos 配置读取失败")
    data = payload.get("data")
    content = data.get("content") if isinstance(data, dict) else data
    if not isinstance(content, str):
        raise NacosIntegrationError("Nacos 配置接口未返回有效正文")
    return content


def _fetch_v2_catalog(
    client: httpx.Client, api_base_url: str, username: str, password: str
) -> list[dict]:
    namespace_path = f"{api_base_url}/v2/console/namespace/list"
    response = client.get(namespace_path)
    access_token: str | None = None
    if response.status_code in {401, 403}:
        access_token = _login_v2(client, api_base_url, username, password)
        response = client.get(namespace_path, params={"accessToken": access_token})
    namespace_payload = _read_api_payload(response)
    namespace_items = namespace_payload.get("data")
    if not isinstance(namespace_items, list):
        raise NacosIntegrationError("Nacos 命名空间响应格式无效")

    namespaces: list[dict] = []
    for item in namespace_items:
        if not isinstance(item, dict):
            continue
        raw_namespace_id = str(item.get("namespace") or "")
        display_name = str(
            item.get("namespaceShowName") or raw_namespace_id or "public"
        )
        params = {"namespaceId": raw_namespace_id}
        if access_token:
            params["accessToken"] = access_token
        config_response = client.get(
            f"{api_base_url}/v2/cs/history/configs", params=params
        )
        if config_response.status_code in {401, 403} and not access_token:
            access_token = _login_v2(client, api_base_url, username, password)
            params["accessToken"] = access_token
            config_response = client.get(
                f"{api_base_url}/v2/cs/history/configs", params=params
            )
        config_payload = _read_api_payload(config_response)
        config_items = config_payload.get("data")
        if not isinstance(config_items, list):
            raise NacosIntegrationError("Nacos 配置目录响应格式无效")

        configs = _sanitize_configs(config_items)
        namespaces.append(
            {
                "namespace_id": raw_namespace_id or "public",
                "namespace_name": display_name,
                "config_count": len(configs),
                "configs": configs,
            }
        )

    return sorted(namespaces, key=lambda item: item["namespace_name"].lower())


def _login_v2(
    client: httpx.Client, api_base_url: str, username: str, password: str
) -> str:
    for login_path in ("/v1/auth/users/login", "/v1/auth/login"):
        response = client.post(
            f"{api_base_url}{login_path}",
            data={"username": username, "password": password},
        )
        if response.status_code == 404:
            continue
        if response.status_code in {401, 403}:
            raise NacosIntegrationError("Nacos 用户名或密码无效")
        if response.status_code >= 400:
            raise NacosIntegrationError("Nacos 登录请求失败")
        try:
            payload = response.json()
        except ValueError as exc:
            raise NacosIntegrationError("Nacos 登录响应格式无效") from exc
        access_token = payload.get("accessToken") if isinstance(payload, dict) else None
        if isinstance(access_token, str) and access_token:
            return access_token
        raise NacosIntegrationError("Nacos 登录响应缺少访问令牌")
    raise NacosIntegrationError("该 Nacos 未提供兼容的登录接口")


def _read_api_payload(response: httpx.Response) -> dict:
    if response.status_code == 404:
        raise _NacosPathUnavailable()
    if response.status_code in {401, 403}:
        raise NacosIntegrationError("Nacos 凭证无权读取配置目录")
    if response.status_code >= 400:
        raise NacosIntegrationError(f"Nacos API 返回 HTTP {response.status_code}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise NacosIntegrationError("Nacos API 响应不是有效 JSON") from exc
    if not isinstance(payload, dict):
        raise NacosIntegrationError("Nacos API 响应格式无效")
    code = payload.get("code")
    if code not in {None, 0, 200}:
        raise NacosIntegrationError("Nacos API 返回失败状态")
    return payload


def _sanitize_configs(items: list) -> list[dict]:
    configs: dict[tuple[str, str], dict] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        data_id = item.get("dataId")
        if not isinstance(data_id, str) or not data_id.strip():
            continue
        group_name = item.get("group") or item.get("groupName") or "DEFAULT_GROUP"
        config_type = item.get("type") or _infer_config_type(data_id)
        key = (str(group_name), data_id)
        configs[key] = {
            "group": str(group_name),
            "data_id": data_id,
            "type": str(config_type).lower(),
        }
    return sorted(
        configs.values(),
        key=lambda item: (item["group"].lower(), item["data_id"].lower()),
    )


def _infer_config_type(data_id: str) -> str:
    suffix = PurePosixPath(data_id).suffix.lstrip(".").lower()
    return suffix or "text"


def _candidate_api_base_urls(base_url: str) -> list[str]:
    parts = urlsplit(base_url.rstrip("/"))
    normalized = urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))
    candidates = [normalized]
    if not parts.path.rstrip("/").endswith("/nacos"):
        candidates.append(f"{normalized}/nacos")
    return candidates
