from unittest import TestCase
from unittest.mock import patch

from pymysql.err import OperationalError

from app import mysql_client


class FakeCursor:
    def __init__(self, rows: list) -> None:
        self.rows = rows
        self.sql = ""
        self.params = None

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def execute(self, sql: str, params=None) -> None:
        self.sql = " ".join(sql.split())
        self.params = params

    def fetchall(self) -> list:
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


class FakeConnection:
    def __init__(self, rows: list) -> None:
        self.fake_cursor = FakeCursor(rows)
        self.closed = False

    def cursor(self) -> FakeCursor:
        return self.fake_cursor

    def close(self) -> None:
        self.closed = True


class MySQLAccountInventoryTests(TestCase):
    def test_maps_safe_account_fields_without_password_hash(self) -> None:
        connection = FakeConnection(
            [
                {
                    "User": "reader",
                    "Host": "10.%",
                    "plugin": "caching_sha2_password",
                    "account_locked": "N",
                    "password_expired": "Y",
                    "authentication_string": "must-not-leak",
                }
            ]
        )
        with patch.object(mysql_client.pymysql, "connect", return_value=connection):
            accounts = mysql_client.fetch_mysql_accounts(
                "mysql://mysql.example.internal:3306", "admin", "secret"
            )

        self.assertIn("FROM mysql.user", connection.fake_cursor.sql)
        self.assertTrue(connection.closed)
        self.assertEqual(accounts[0]["user_identity"], "'reader'@'10.%'")
        self.assertEqual(accounts[0]["username"], "reader")
        self.assertEqual(accounts[0]["host"], "10.%")
        self.assertIn("认证插件：caching_sha2_password", accounts[0]["comment"])
        self.assertIn("密码已过期", accounts[0]["comment"])
        self.assertNotIn("authentication_string", str(accounts))
        self.assertNotIn("must-not-leak", str(accounts))

    def test_returns_safe_authentication_error(self) -> None:
        with patch.object(
            mysql_client.pymysql,
            "connect",
            side_effect=OperationalError(1045, "sensitive upstream detail"),
        ):
            with self.assertRaisesRegex(
                mysql_client.MySQLIntegrationError,
                "MySQL 管理凭证认证失败",
            ):
                mysql_client.fetch_mysql_accounts(
                    "mysql://mysql.example.internal:3306", "admin", "secret"
                )

    def test_verifies_password_with_exact_current_user_identity(self) -> None:
        connection = FakeConnection([("reader@10.%",)])
        with patch.object(mysql_client.pymysql, "connect", return_value=connection) as connect:
            matched = mysql_client.verify_mysql_account_password(
                "mysql://mysql.example.internal:3306",
                "'reader'@'10.%'",
                "candidate",
            )

        self.assertTrue(matched)
        self.assertEqual(connection.fake_cursor.sql, "SELECT CURRENT_USER()")
        self.assertEqual(connect.call_args.kwargs["user"], "reader")
        self.assertEqual(connect.call_args.kwargs["password"], "candidate")
        self.assertTrue(connection.closed)

    def test_rejects_password_when_mysql_rejects_authentication(self) -> None:
        with patch.object(
            mysql_client.pymysql,
            "connect",
            side_effect=OperationalError(1045, "upstream detail"),
        ):
            matched = mysql_client.verify_mysql_account_password(
                "mysql://mysql.example.internal:3306",
                "'reader'@'%'",
                "wrong-candidate",
            )

        self.assertFalse(matched)

    def test_rejects_password_when_mysql_matches_a_different_host_identity(self) -> None:
        connection = FakeConnection([("reader@10.%",)])
        with patch.object(mysql_client.pymysql, "connect", return_value=connection):
            matched = mysql_client.verify_mysql_account_password(
                "mysql://mysql.example.internal:3306",
                "'reader'@'%'",
                "candidate",
            )

        self.assertFalse(matched)

    def test_sets_password_for_the_exact_quoted_identity(self) -> None:
        connection = FakeConnection([])
        with patch.object(mysql_client.pymysql, "connect", return_value=connection):
            mysql_client.set_mysql_account_password(
                "mysql://mysql.example.internal:3306",
                "admin",
                "admin-secret",
                "'reader'@'10.%'",
                "replacement",
            )

        self.assertEqual(
            connection.fake_cursor.sql,
            "ALTER USER 'reader'@'10.%' IDENTIFIED BY %s",
        )
        self.assertEqual(connection.fake_cursor.params, ("replacement",))
        self.assertTrue(connection.closed)

    def test_rejects_invalid_user_identity_before_connecting(self) -> None:
        with patch.object(mysql_client.pymysql, "connect") as connect:
            with self.assertRaisesRegex(
                mysql_client.MySQLIntegrationError,
                "MySQL 用户标识格式无效",
            ):
                mysql_client.set_mysql_account_password(
                    "mysql://mysql.example.internal:3306",
                    "admin",
                    "admin-secret",
                    "reader; DROP USER root",
                    "replacement",
                )

        connect.assert_not_called()
