from types import SimpleNamespace
import time

import pymysql
import pytest

from app import db
from app.request_metrics import RequestMetrics, current_metrics


@pytest.fixture
def database(monkeypatch):
    db.dispose_pools()
    connections = []
    committed = []

    class Cursor:
        def __init__(self, connection): self.connection = connection; self.closed = False
        def execute(self, sql, params=None):
            self.connection.executions.append(sql)
            if sql == "disconnect":
                self.connection.closed = True
                raise pymysql.OperationalError(2013, "lost connection")
            if sql == "syntax": raise pymysql.ProgrammingError(1064, "invalid SQL")
            if sql == "insert": self.connection.pending.append(params)
        def executemany(self, sql, params):
            for item in params: self.execute(sql, item)
        def fetchall(self): return [{"count":len(committed)+len(self.connection.pending)}]
        def fetchone(self): return self.fetchall()[0]
        def close(self): self.closed = True

    class Connection:
        def __init__(self, options):
            self.options = options; self.closed = False; self.pending = []; self.executions = []; self.rollbacks = 0
        def cursor(self): return Cursor(self)
        def commit(self): committed.extend(self.pending); self.pending.clear()
        def rollback(self): self.rollbacks += 1; self.pending.clear()
        def close(self): self.closed = True
        def ping(self, reconnect=False):
            assert reconnect is False
            if self.closed: raise pymysql.OperationalError(2006, "server has gone away")

    def connect(**options):
        connection = Connection(options); connections.append(connection); return connection

    monkeypatch.setattr(db.pymysql, "connect", connect)
    monkeypatch.setattr(db, "settings", SimpleNamespace(mysql_host="test", mysql_port=3306, mysql_user="user",
        mysql_password="not-logged", mysql_database="infraops", mysql_pool_size=1, mysql_pool_max_overflow=0,
        mysql_pool_timeout_seconds=0.05, mysql_pool_recycle_seconds=300))
    yield connections, committed
    db.dispose_pools()


def test_pool_reuses_connections_and_rolls_back_uncommitted_state(database):
    connections, committed = database
    first = db.get_connection()
    cursor = first.cursor(); cursor.execute("insert", ("uncommitted",))
    first.close(); first.close()
    assert cursor._closed
    second = db.get_connection()
    assert len(connections) == 1 and not connections[0].closed
    assert second.cursor().fetchone()["count"] == 0
    with pytest.raises(db.DatabaseUnavailable): cursor.execute("insert", ("late",))
    with second.cursor() as cur: cur.execute("insert", ("saved",))
    second.commit(); second.close()
    assert committed == [("saved",)]


def test_capacity_is_bounded_and_wait_times_out(database):
    first = db.get_connection()
    started = time.perf_counter()
    with pytest.raises(db.DatabaseBusy): db.get_connection()
    assert time.perf_counter()-started < 1
    first.close()
    db.get_connection().close()


def test_disconnect_is_replaced_on_checkout_but_failed_sql_is_not_replayed(database):
    connections, _ = database
    db.get_connection().close()
    connections[0].closed = True
    lease = db.get_connection()
    assert len(connections) == 2
    with pytest.raises(db.DatabaseUnavailable): lease.cursor().execute("disconnect")
    lease.rollback(); lease.close()
    assert connections[1].executions == ["disconnect"]
    db.get_connection().close()
    assert len(connections) == 3


def test_sql_errors_preserve_transaction_cleanup_and_pool_reuse(database):
    connections, _ = database
    lease = db.get_connection()
    with pytest.raises(pymysql.ProgrammingError): lease.cursor().execute("syntax")
    lease.close()
    db.get_connection().close()
    assert len(connections) == 1


def test_databases_use_separate_pools_and_batch_reads_share_one_lease(database):
    connections, _ = database
    results = db.execute_queries([("select", ()), ("select", ())])
    assert len(results) == 2 and len(connections) == 1
    db.get_connection(database=None).close()
    db.get_connection(database="other").close()
    assert len(connections) == 3
    assert [item.options.get("database") for item in connections] == ["infraops", None, "other"]


def test_metrics_report_counts_and_durations_without_sql_or_parameters(database):
    metrics = RequestMetrics(); token = current_metrics.set(metrics)
    try:
        db.execute_query("select-private-text", ("private-password",))
        db.execute_query("select-private-text", ("private-password",))
        result = metrics.snapshot()
        assert result["db_checkouts"] == 2 and result["db_queries"] == 2 and result["db_new_connections"] == 1
        assert "private" not in str(result)
        assert result["db_sql_ms"] >= 0 and result["db_acquire_ms"] >= 0
    finally: current_metrics.reset(token)
