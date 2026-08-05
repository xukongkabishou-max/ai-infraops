from pathlib import Path
import sys


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.db import execute_query
from app.middleware_crypto import decrypt_middleware_password
from app.nacos_client import fetch_nacos_catalog


def main() -> None:
    instances = execute_query(
        """
        SELECT id, base_url, username, password_ciphertext, password_nonce
        FROM middleware_instances
        WHERE middleware_type = 'nacos' AND status <> 'disabled'
        ORDER BY id
        """
    )
    print({"instance_count": len(instances)})
    if not instances:
        return

    instance = instances[0]
    password = decrypt_middleware_password(
        instance["password_ciphertext"], instance["password_nonce"]
    )
    catalog = fetch_nacos_catalog(
        instance["base_url"], instance["username"], password
    )
    formats = {
        config["type"]
        for namespace in catalog
        for config in namespace["configs"]
    }
    print(
        {
            "namespace_count": len(catalog),
            "config_count": sum(item["config_count"] for item in catalog),
            "format_count": len(formats),
        }
    )


if __name__ == "__main__":
    main()
