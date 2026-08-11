import httpx

from app.nacos_client import _fetch_v2_config_content


def test_fetches_v2_config_content_with_public_namespace() -> None:
    requested_params: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        requested_params.update(dict(request.url.params))
        return httpx.Response(
            200,
            json={"code": 0, "message": "success", "data": "app:\n  name: secret"},
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        content = _fetch_v2_config_content(
            client,
            "http://nacos.example/nacos",
            "user",
            "password",
            "public",
            "DEFAULT_GROUP",
            "application.yaml",
        )

    assert content == "app:\n  name: secret"
    assert requested_params == {
        "namespaceId": "",
        "group": "DEFAULT_GROUP",
        "dataId": "application.yaml",
    }


def test_fetches_content_from_object_payload() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": 0, "data": {"content": '{"a":1}'}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        content = _fetch_v2_config_content(
            client,
            "http://nacos.example/nacos",
            "user",
            "password",
            "dev",
            "DEFAULT_GROUP",
            "application.json",
        )

    assert content == '{"a":1}'
