from collections.abc import Iterator
import os
from threading import Lock

import pymysql
from pymysql.cursors import DictCursor
from sqlalchemy.dialects.mysql.pymysql import MySQLDialect_pymysql
from sqlalchemy.exc import TimeoutError as PoolTimeout
from sqlalchemy.pool import QueuePool

from .config import settings
from .request_metrics import add_metric, measure

DEFAULT_DATABASE = object()
_pools: dict[tuple[int, str | None], QueuePool] = {}
_pool_lock = Lock()
_dialect = MySQLDialect_pymysql(dbapi=pymysql)


class DatabaseBusy(RuntimeError):
    pass


class DatabaseUnavailable(RuntimeError):
    pass


class _Cursor:
    def __init__(self, connection, cursor):
        self.connection = connection
        self._cursor = cursor
        self._closed = False

    def execute(self, *args, **kwargs):
        add_metric("db_queries")
        return self.connection._run(self._cursor.execute, *args, **kwargs)

    def executemany(self, *args, **kwargs):
        add_metric("db_queries")
        return self.connection._run(self._cursor.executemany, *args, **kwargs)

    def close(self):
        if self._closed:
            return
        try:
            self._cursor.close()
        finally:
            self._closed = True
            self.connection._cursors.discard(self)

    def __getattr__(self, name):
        return getattr(self._cursor, name)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def __iter__(self):
        return iter(self._cursor)


class _Connection:
    def __init__(self, lease):
        self._lease = lease
        self._closed = False
        self._cursors: set[_Cursor] = set()

    def _run(self, operation, *args, **kwargs):
        if self._closed or not self._lease.is_valid:
            raise DatabaseUnavailable("数据库连接已关闭")
        with measure("db_sql_ms"):
            try:
                return operation(*args, **kwargs)
            except pymysql.Error as exc:
                if _dialect.is_disconnect(exc, self._lease.dbapi_connection, None):
                    self._lease.invalidate(exc)
                    raise DatabaseUnavailable("数据库连接中断，请重试") from None
                raise

    def cursor(self, *args, **kwargs):
        if self._closed or not self._lease.is_valid:
            raise DatabaseUnavailable("数据库连接已关闭")
        cursor = _Cursor(self, self._lease.cursor(*args, **kwargs))
        self._cursors.add(cursor)
        return cursor

    def commit(self):
        return self._run(self._lease.commit)

    def rollback(self):
        if not self._lease.is_valid:
            return
        return self._run(self._lease.rollback)

    def close(self):
        if self._closed:
            return
        with measure("db_release_ms"):
            try:
                for cursor in tuple(self._cursors):
                    cursor.close()
            finally:
                self._closed = True
                self._lease.close()

    def __getattr__(self, name):
        return getattr(self._lease, name)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def _create_pool(database):
    if settings.mysql_pool_size < 1 or settings.mysql_pool_max_overflow < 0 or settings.mysql_pool_timeout_seconds <= 0 or settings.mysql_pool_recycle_seconds <= 0:
        raise RuntimeError("MySQL 连接池配置无效")
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
    if database:
        options["database"] = database

    def connect():
        with measure("db_connect_ms"):
            connection = pymysql.connect(**options)
        add_metric("db_new_connections")
        return connection

    return QueuePool(connect, pool_size=settings.mysql_pool_size,
                     max_overflow=settings.mysql_pool_max_overflow,
                     timeout=settings.mysql_pool_timeout_seconds,
                     recycle=settings.mysql_pool_recycle_seconds,
                     reset_on_return="rollback", use_lifo=True, pre_ping=True, dialect=_dialect)


def get_connection(database: str | None | object = DEFAULT_DATABASE):
    database = settings.mysql_database if database is DEFAULT_DATABASE else database
    key = (os.getpid(), database)
    with _pool_lock:
        if key not in _pools:
            _pools[key] = _create_pool(database)
        pool = _pools[key]
    add_metric("db_checkouts")
    with measure("db_acquire_ms"):
        try:
            return _Connection(pool.connect())
        except PoolTimeout:
            raise DatabaseBusy("数据库连接繁忙，请稍后重试") from None
        except (pymysql.Error, OSError):
            raise DatabaseUnavailable("数据库暂时不可用，请稍后重试") from None


def dispose_pools():
    with _pool_lock:
        pools = list(_pools.values())
        _pools.clear()
    for pool in pools:
        pool.dispose()


def execute_query(sql: str, params: tuple | dict | None = None) -> list[dict]:
    connection = get_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            return list(cursor.fetchall())
    finally:
        connection.close()


def execute_queries(statements: list[tuple[str, tuple]]) -> list[list[dict]]:
    connection = get_connection()
    try:
        with connection.cursor() as cursor:
            results = []
            for sql, params in statements:
                cursor.execute(sql, params)
                results.append(list(cursor.fetchall()))
            return results
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
