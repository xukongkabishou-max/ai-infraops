from unittest import TestCase

from pydantic import ValidationError

from app.schemas import MiddlewareInstanceCreateRequest, MiddlewareInstanceUpdateRequest


class MiddlewareInstanceCreateRequestTests(TestCase):
    def test_normalizes_mysql_address_and_dashboard_url(self) -> None:
        payload = MiddlewareInstanceCreateRequest(
            middleware_type="mysql",
            environment_name="开发环境",
            instance_name="开发环境 MySQL",
            base_url="mysql.internal:3306",
            dashboard_url="HTTP://grafana.internal:3000/d/mysql?from=now-12h&refresh=1m",
            username="admin",
            password="secret",
        )

        self.assertEqual(payload.base_url, "mysql://mysql.internal:3306")
        self.assertEqual(
            payload.dashboard_url,
            "http://grafana.internal:3000/d/mysql?from=now-12h&refresh=1m",
        )

    def test_requires_mysql_dashboard_url(self) -> None:
        with self.assertRaisesRegex(
            ValidationError, "MySQL 实例必须填写 Grafana 仪表盘地址"
        ):
            MiddlewareInstanceCreateRequest(
                middleware_type="mysql",
                environment_name="开发环境",
                instance_name="开发环境 MySQL",
                base_url="mysql.internal:3306",
                username="admin",
                password="secret",
            )

    def test_does_not_keep_dashboard_url_for_other_middleware(self) -> None:
        payload = MiddlewareInstanceCreateRequest(
            middleware_type="doris",
            environment_name="开发环境",
            instance_name="开发环境 Doris",
            base_url="doris.internal:9030",
            dashboard_url="http://grafana.internal:3000/d/mysql",
            username="admin",
            password="secret",
        )

        self.assertEqual(payload.dashboard_url, "")

    def test_update_allows_blank_password_to_keep_existing_credential(self) -> None:
        payload = MiddlewareInstanceUpdateRequest(
            middleware_type="mysql",
            environment_name="开发环境",
            instance_name="开发环境 MySQL",
            base_url="mysql.internal:3306",
            dashboard_url="https://grafana.internal/d/mysql?refresh=1m",
            username="admin",
        )

        self.assertEqual(payload.password, "")
