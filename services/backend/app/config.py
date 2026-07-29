import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[3]
load_dotenv(ROOT_DIR / ".env")


@dataclass(frozen=True)
class Settings:
    mysql_host: str = os.getenv("MYSQL_HOST", "127.0.0.1")
    mysql_port: int = int(os.getenv("MYSQL_PORT", "3306"))
    mysql_database: str = os.getenv("MYSQL_DATABASE", "infraops")
    mysql_user: str = os.getenv("MYSQL_USER", "root")
    mysql_password: str = os.getenv("MYSQL_PWD") or os.getenv("_MYSQL_PWD", "")
    redis_host: str = os.getenv("REDIS_HOST", "127.0.0.1")
    redis_port: int = int(os.getenv("REDIS_PORT", "6379"))
    redis_password: str = os.getenv("REDIS_PASSWORD", "")
    redis_db: int = int(os.getenv("REDIS_DB", "0"))
    redis_tls: bool = os.getenv("REDIS_TLS", "false").lower() in {"1", "true", "yes"}
    session_ttl_seconds: int = int(os.getenv("SESSION_TTL_SECONDS", "86400"))
    k8s_connect_timeout_seconds: int = int(os.getenv("K8S_CONNECT_TIMEOUT_SECONDS", "5"))
    k8s_read_timeout_seconds: int = int(os.getenv("K8S_READ_TIMEOUT_SECONDS", "20"))
    k8s_credential_encryption_key: str = os.getenv("K8S_CREDENTIAL_ENCRYPTION_KEY", "")
    cors_origins: tuple[str, ...] = (
        "http://localhost:3000",
        "http://localhost:3001",
    )


settings = Settings()
