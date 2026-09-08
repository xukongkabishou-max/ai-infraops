from unittest import TestCase

import httpx
from pydantic import ValidationError

from app.monitoring_platform_client import (
    MonitoringPlatformProbeError,
    probe_monitoring_platform,
)
from app.schemas import MonitoringPlatformRequest


class MonitoringPlatformSchemaTests(TestCase):
    def test_normalizes_platform_url(self) -> None:
        payload = MonitoringPlatformRequest(
            name=" DevOps 监控平台 ",
            platform_type="backstage",
            base_url="HTTP://monitoring.internal:7008",
        )

        self.assertEqual(payload.name, "DevOps 监控平台")
        self.assertEqual(payload.base_url, "http://monitoring.internal:7008/")

    def test_rejects_credentials_in_url(self) -> None:
        with self.assertRaisesRegex(ValidationError, "不允许包含用户名或密码"):
            MonitoringPlatformRequest(
                name="监控平台",
                base_url="http://admin:secret@monitoring.internal/",
            )


class MonitoringPlatformProbeTests(TestCase):
    def test_accepts_successful_response(self) -> None:
        transport = httpx.MockTransport(
            lambda request: httpx.Response(200, request=request, text="ok")
        )

        probe_monitoring_platform("http://monitoring.internal/", transport=transport)

    def test_formats_http_error(self) -> None:
        transport = httpx.MockTransport(
            lambda request: httpx.Response(503, request=request, text="unavailable")
        )

        with self.assertRaisesRegex(MonitoringPlatformProbeError, "HTTP 503"):
            probe_monitoring_platform("http://monitoring.internal/", transport=transport)
