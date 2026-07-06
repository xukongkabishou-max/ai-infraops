from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import urlopen


METRICS_TIMEOUT_SECONDS = 8
CPU_USAGE_SAMPLE_SECONDS = 1.0


@dataclass(frozen=True)
class ScrapeResult:
    status: str
    normalized_url: str
    hostname: str
    public_ip: str
    error: str | None
    metrics: dict | None


def normalize_exporter_url(raw_url: str) -> str:
    url = raw_url.strip()
    if not url.startswith(("http://", "https://")):
        url = f"http://{url}"
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    if not path or path == "":
        url = url.rstrip("/") + "/metrics"
    elif path != "/metrics":
        url = url.rstrip("/") + "/metrics"
    return url


def public_ip_from_url(url: str) -> str:
    hostname = urlparse(url).hostname or ""
    return hostname


def scrape_node_exporter(raw_url: str, include_cpu_usage: bool = False) -> ScrapeResult:
    url = normalize_exporter_url(raw_url)
    public_ip = public_ip_from_url(url)
    try:
        content = fetch_metrics(url)
        cpu_usage = None
        sample_seconds = 0.0
        if include_cpu_usage:
            first_cpu_seconds = collect_cpu_mode_seconds(content)
            start = time.monotonic()
            time.sleep(CPU_USAGE_SAMPLE_SECONDS)
            content = fetch_metrics(url)
            sample_seconds = time.monotonic() - start
            second_cpu_seconds = collect_cpu_mode_seconds(content)
            cpu_usage = calculate_cpu_usage_percent(first_cpu_seconds, second_cpu_seconds)
    except (OSError, URLError, TimeoutError) as exc:
        return ScrapeResult(
            status="unreachable",
            normalized_url=url,
            hostname="",
            public_ip=public_ip,
            error=f"{type(exc).__name__}: {exc}",
            metrics=None,
        )

    metrics = parse_metrics(content)
    if cpu_usage is not None:
        metrics["cpu"]["usagePercent"] = cpu_usage
        metrics["cpu"]["sampleSeconds"] = round(sample_seconds, 2)
    return ScrapeResult(
        status="active",
        normalized_url=url,
        hostname=metrics.get("hostname", ""),
        public_ip=public_ip,
        error=None,
        metrics=metrics,
    )


def fetch_metrics(url: str) -> str:
    with urlopen(url, timeout=METRICS_TIMEOUT_SECONDS) as response:
        return response.read().decode("utf-8", errors="replace")


def parse_metrics(content: str) -> dict:
    metric_values: dict[str, float] = {}
    cpu_labels: set[str] = set()
    hostname = ""

    for line in content.splitlines():
        if not line or line.startswith("#"):
            continue

        if line.startswith("node_uname_info"):
            match = re.search(r'nodename="([^"]+)"', line)
            if match:
                hostname = match.group(1)
            continue

        if line.startswith("node_load5 "):
            metric_values["load5"] = _metric_number(line)
            continue

        if line.startswith("node_cpu_seconds_total"):
            match = re.search(r'cpu="([^"]+)"', line)
            if match:
                cpu_labels.add(match.group(1))
            continue

        for name in (
            "node_memory_MemTotal_bytes",
            "node_memory_MemFree_bytes",
            "node_memory_MemAvailable_bytes",
        ):
            if line.startswith(f"{name} "):
                metric_values[name] = _metric_number(line)
                break

        if 'mountpoint="/"' in line:
            if line.startswith("node_filesystem_size_bytes"):
                metric_values["root_size"] = _metric_number(line)
            elif line.startswith("node_filesystem_avail_bytes"):
                metric_values["root_avail"] = _metric_number(line)
            elif line.startswith("node_filesystem_free_bytes"):
                metric_values["root_free"] = _metric_number(line)

    mem_total = metric_values.get("node_memory_MemTotal_bytes", 0.0)
    mem_free = metric_values.get("node_memory_MemFree_bytes", 0.0)
    mem_available = metric_values.get("node_memory_MemAvailable_bytes", 0.0)
    mem_used = max(mem_total - mem_available, 0.0)
    root_size = metric_values.get("root_size", 0.0)
    root_avail = metric_values.get("root_avail", metric_values.get("root_free", 0.0))
    cpu_core_count = len(cpu_labels)
    load5 = metric_values.get("load5", 0.0)
    load5_percent = (load5 / cpu_core_count * 100) if cpu_core_count else 0.0
    memory_usage_percent = (mem_used / mem_total * 100) if mem_total else 0.0
    root_used = max(root_size - root_avail, 0.0)
    root_usage_percent = (root_used / root_size * 100) if root_size else 0.0

    return {
        "scrapedAt": datetime.now(timezone.utc).isoformat(),
        "hostname": hostname,
        "load5": round(load5, 2),
        "cpu": {
            "coreCount": cpu_core_count,
            "load5": round(load5, 2),
            "load5Percent": round(load5_percent, 2),
            "usagePercent": 0.0,
            "sampleSeconds": 0.0,
        },
        "memory": {
            "totalBytes": int(mem_total),
            "usedBytes": int(mem_used),
            "freeBytes": int(mem_free),
            "availableBytes": int(mem_available),
            "usagePercent": round(memory_usage_percent, 2),
            "totalHuman": format_bytes(mem_total),
            "usedHuman": format_bytes(mem_used),
            "freeHuman": format_bytes(mem_free),
            "availableHuman": format_bytes(mem_available),
        },
        "rootDisk": {
            "totalBytes": int(root_size),
            "usedBytes": int(root_used),
            "availableBytes": int(root_avail),
            "usagePercent": round(root_usage_percent, 2),
            "totalHuman": format_bytes(root_size),
            "usedHuman": format_bytes(root_used),
            "availableHuman": format_bytes(root_avail),
        },
    }


def collect_cpu_mode_seconds(content: str) -> dict[tuple[str, str], float]:
    values: dict[tuple[str, str], float] = {}
    for line in content.splitlines():
        if not line.startswith("node_cpu_seconds_total"):
            continue
        cpu_match = re.search(r'cpu="([^"]+)"', line)
        mode_match = re.search(r'mode="([^"]+)"', line)
        if cpu_match and mode_match:
            values[(cpu_match.group(1), mode_match.group(1))] = _metric_number(line)
    return values


def calculate_cpu_usage_percent(
    before: dict[tuple[str, str], float],
    after: dict[tuple[str, str], float],
) -> float:
    total_delta = 0.0
    idle_delta = 0.0
    for key, after_value in after.items():
        before_value = before.get(key)
        if before_value is None:
            continue
        delta = max(after_value - before_value, 0.0)
        total_delta += delta
        if key[1] in {"idle", "iowait"}:
            idle_delta += delta
    if total_delta <= 0:
        return 0.0
    return round((1 - idle_delta / total_delta) * 100, 2)


def _metric_number(line: str) -> float:
    return float(line.rsplit(" ", 1)[-1])


def format_bytes(value: float) -> str:
    units = ("B", "KiB", "MiB", "GiB", "TiB", "PiB")
    size = float(value)
    for unit in units:
        if abs(size) < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PiB"
