from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from threading import Lock
from time import perf_counter


@dataclass
class RequestMetrics:
    values: dict[str, float] = field(default_factory=dict)
    lock: Lock = field(default_factory=Lock)

    def add(self, name: str, value: float):
        with self.lock:
            self.values[name] = self.values.get(name, 0) + value

    def snapshot(self):
        with self.lock:
            return {name: round(value, 2) for name, value in self.values.items()}


current_metrics: ContextVar[RequestMetrics | None] = ContextVar("request_metrics", default=None)


def add_metric(name: str, value: float = 1):
    metrics = current_metrics.get()
    if metrics is not None:
        metrics.add(name, value)


@contextmanager
def measure(name: str):
    started = perf_counter()
    try:
        yield
    finally:
        add_metric(name, (perf_counter() - started) * 1000)
