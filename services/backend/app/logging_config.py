from __future__ import annotations

import json
import logging
import re
import time
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from .config import ROOT_DIR, settings


request_id_context: ContextVar[str] = ContextVar("request_id", default="-")
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
LOG_RECORD_FIELDS = (
    "event",
    "method",
    "path",
    "status_code",
    "duration_ms",
    "db_acquire_ms",
    "db_connect_ms",
    "db_sql_ms",
    "db_release_ms",
    "db_checkouts",
    "db_new_connections",
    "db_queries",
    "audit_ms",
    "redis_ms",
    "host_id",
    "namespace",
    "result_count",
    "user_id",
    "middleware_instance_id",
    "middleware_type",
    "account_count",
    "target_url",
    "error_type",
)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_context.get(),
        }
        for field in LOG_RECORD_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging() -> Path:
    log_dir = Path(settings.log_dir)
    if not log_dir.is_absolute():
        log_dir = ROOT_DIR / log_dir
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "backend.log"

    formatter = JsonFormatter()
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=settings.log_file_max_bytes,
        backupCount=settings.log_file_backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    logger = logging.getLogger("infraops")
    logger.handlers.clear()
    logger.setLevel(settings.log_level)
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    logger.propagate = False
    return log_file


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        from .request_metrics import RequestMetrics, current_metrics
        metrics = RequestMetrics()
        metrics_token = current_metrics.set(metrics)
        supplied_request_id = request.headers.get("X-Request-ID", "")
        request_id = (
            supplied_request_id
            if REQUEST_ID_PATTERN.fullmatch(supplied_request_id)
            else uuid.uuid4().hex
        )
        token = request_id_context.set(request_id)
        logger = logging.getLogger("infraops.http")
        started_at = time.perf_counter()
        try:
            response = await call_next(request)
            duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Response-Time-Ms"] = str(duration_ms)
            timings = metrics.snapshot()
            response.headers["Server-Timing"] = ", ".join([
                f"total;dur={duration_ms}",
                *(f"{name};dur={timings.get(name + '_ms', 0)}" for name in ("db_acquire", "db_connect", "db_sql", "db_release", "redis", "audit")),
                f"db_queries;desc=\"{int(timings.get('db_queries', 0))} queries\"",
                f"db_new_connections;desc=\"{int(timings.get('db_new_connections', 0))} connections\"",
            ])
            logger.info(
                "请求完成",
                extra={
                    "event": "http_request_completed",
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": duration_ms,
                    **timings,
                },
            )
            return response
        except Exception as exc:
            duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
            logger.exception(
                "请求处理异常",
                extra={
                    "event": "http_request_failed",
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": 500,
                    "duration_ms": duration_ms,
                    "error_type": type(exc).__name__,
                    **metrics.snapshot(),
                },
            )
            raise
        finally:
            request_id_context.reset(token)
            current_metrics.reset(metrics_token)
