from pathlib import Path
import sys

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.config import ROOT_DIR, settings
from app.db import get_connection


def split_sql(sql_text: str) -> list[str]:
    statements: list[str] = []
    current: list[str] = []
    for line in sql_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        current.append(line)
        if stripped.endswith(";"):
            statements.append("\n".join(current).strip().rstrip(";"))
            current = []
    if current:
        statements.append("\n".join(current).strip())
    return statements


def main() -> None:
    sql_path = ROOT_DIR / "services" / "backend" / "sql" / "init.sql"
    sql_text = sql_path.read_text(encoding="utf-8")

    connection = get_connection(database=None)
    try:
        with connection.cursor() as cursor:
            for statement in split_sql(sql_text):
                cursor.execute(statement)
        connection.commit()
    finally:
        connection.close()

    print(f"initialized database `{settings.mysql_database}` on {settings.mysql_host}:{settings.mysql_port}")


if __name__ == "__main__":
    main()
