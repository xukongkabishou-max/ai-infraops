from unittest import TestCase

from pydantic import ValidationError

from app.schemas import MiddlewareInstanceCreateRequest


class MiddlewareInstanceCreateRequestTests(TestCase):
    def test_normalizes_mysql_address_and_exporter_url(self) -> None:
        payload = MiddlewareInstanceCreateRequest(
            middleware_type="mysql",
            environment_name="开发环境",
            instance_name="开发环境 MySQL",
            base_url="mysql.internal:3306",
            exporter_url="HTTP://metrics.internal:9104/metrics/",
            username="admin",
            password="secret",
        )

        self.assertEqual(payload.base_url, "mysql://mysql.internal:3306")
        self.assertEqual(
            payload.exporter_url, "http://metrics.internal:9104/metrics"
        )

    def test_requires_mysql_exporter_url(self) -> None:
        with self.assertRaisesRegex(
            ValidationError, "MySQL 实例必须填写 mysql-exporter URL"
        ):
            MiddlewareInstanceCreateRequest(
                middleware_type="mysql",
                environment_name="开发环境",
                instance_name="开发环境 MySQL",
                base_url="mysql.internal:3306",
                username="admin",
                password="secret",
            )

    def test_does_not_keep_exporter_url_for_other_middleware(self) -> None:
        payload = MiddlewareInstanceCreateRequest(
            middleware_type="doris",
            environment_name="开发环境",
            instance_name="开发环境 Doris",
            base_url="doris.internal:9030",
            exporter_url="http://metrics.internal:9104/metrics",
            username="admin",
            password="secret",
        )

        self.assertEqual(payload.exporter_url, "")
