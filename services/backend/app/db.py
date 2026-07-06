from collections.abc import Iterator

import pymysql
from pymysql.cursors import DictCursor

from .config import settings

DEFAULT_DATABASE = object()


def get_connection(database: str | None | object = DEFAULT_DATABASE):
    options = dict(
        host=settings.mysql_host,
        port=settings.mysql_port,
        user=settings.mysql_user,
        password=settings.mysql_password,
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=False,
        connect_timeout=8,
        read_timeout=15,
        write_timeout=15,
    )
    if database is DEFAULT_DATABASE:
        options["database"] = settings.mysql_database
    elif database:
        options["database"] = database
    return pymysql.connect(**options)


def execute_query(sql: str, params: tuple | dict | None = None) -> list[dict]:
    connection = get_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            return list(cursor.fetchall())
    finally:
        connection.close()


def transaction() -> Iterator:
    connection = get_connection()
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
