from unittest import TestCase
from unittest.mock import patch

from pymysql.err import OperationalError

from app import doris_client


class FakeCursor:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.sql = ""

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def execute(self, sql: str) -> None:
        self.sql = sql

    def fetchall(self) -> list[dict]:
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


class FakeConnection:
    def __init__(self, rows: list[dict]) -> None:
        self.fake_cursor = FakeCursor(rows)
        self.closed = False

    def cursor(self) -> FakeCursor:
        return self.fake_cursor

    def close(self) -> None:
        self.closed = True

    def escape(self, value: str) -> str:
        return "'" + value.replace("'", "\\'") + "'"


class DorisAccountInventoryTests(TestCase):
    def test_maps_accounts_and_drops_password_column(self) -> None:
        connection = FakeConnection(
            [
                {
                    "UserIdentity": "'reader'@'10.%'",
                    "Comment": "只读账号",
                    "Password": "Yes",
                    "Roles": "analytics_reader",
                    "GlobalPrivs": "NULL",
                    "DatabasePrivs": "internal.analytics: Select_priv",
                    "TablePrivs": None,
                }
            ]
        )
        with patch.object(doris_client.pymysql, "connect", return_value=connection) as connect:
            accounts = doris_client.fetch_doris_accounts(
                "mysql://doris.example.internal:9030", "admin", "secret"
            )

        self.assertEqual(connection.fake_cursor.sql, "SHOW ALL GRANTS")
        self.assertTrue(connection.closed)
        connect.assert_called_once()
        self.assertEqual(accounts[0]["username"], "reader")
        self.assertEqual(accounts[0]["host"], "10.%")
        self.assertEqual(accounts[0]["roles"], ["analytics_reader"])
        self.assertEqual(
            accounts[0]["privileges"],
            [{"scope": "数据库权限", "value": "internal.analytics: Select_priv"}],
        )
        self.assertNotIn("password", str(accounts).lower())

    def test_returns_safe_authentication_error(self) -> None:
        with patch.object(
            doris_client.pymysql,
            "connect",
            side_effect=OperationalError(1045, "sensitive upstream detail"),
        ):
            with self.assertRaisesRegex(
                doris_client.DorisIntegrationError,
                "Doris 凭证认证失败",
            ):
                doris_client.fetch_doris_accounts(
                    "mysql://doris.example.internal:9030", "admin", "secret"
                )

    def test_verifies_password_with_exact_current_user_identity(self) -> None:
        connection = FakeConnection([("reader@10.%",)])
        with patch.object(doris_client.pymysql, "connect", return_value=connection) as connect:
            matched = doris_client.verify_doris_account_password(
                "mysql://doris.example.internal:9030",
                "'reader'@'10.%'",
                "candidate",
            )

        self.assertTrue(matched)
        self.assertEqual(connection.fake_cursor.sql, "SELECT CURRENT_USER()")
        self.assertEqual(connect.call_args.kwargs["user"], "reader")
        self.assertEqual(connect.call_args.kwargs["password"], "candidate")
        self.assertTrue(connection.closed)

    def test_rejects_password_when_doris_rejects_authentication(self) -> None:
        with patch.object(
            doris_client.pymysql,
            "connect",
            side_effect=OperationalError(1045, "upstream detail"),
        ):
            matched = doris_client.verify_doris_account_password(
                "mysql://doris.example.internal:9030",
                "'reader'@'%'",
                "wrong-candidate",
            )

        self.assertFalse(matched)

    def test_rejects_password_when_doris_matches_a_different_host_identity(self) -> None:
        connection = FakeConnection([("reader@10.%",)])
        with patch.object(doris_client.pymysql, "connect", return_value=connection):
            matched = doris_client.verify_doris_account_password(
                "mysql://doris.example.internal:9030",
                "'reader'@'%'",
                "candidate",
            )

        self.assertFalse(matched)

    def test_sets_password_for_the_exact_quoted_identity(self) -> None:
        connection = FakeConnection([])
        with patch.object(doris_client.pymysql, "connect", return_value=connection):
            doris_client.set_doris_account_password(
                "mysql://doris.example.internal:9030",
                "admin",
                "admin-secret",
                "'reader'@'10.%'",
                "replacement",
            )

        self.assertEqual(
            connection.fake_cursor.sql,
            "SET PASSWORD FOR 'reader'@'10.%' = PASSWORD('replacement')",
        )
        self.assertTrue(connection.closed)

    def test_rejects_invalid_user_identity_before_connecting(self) -> None:
        with patch.object(doris_client.pymysql, "connect") as connect:
            with self.assertRaisesRegex(
                doris_client.DorisIntegrationError,
                "Doris 用户标识格式无效",
            ):
                doris_client.set_doris_account_password(
                    "mysql://doris.example.internal:9030",
                    "admin",
                    "admin-secret",
                    "reader; DROP USER root",
                    "replacement",
                )

        connect.assert_not_called()
