import json

import pytest

from app.nacos_config_redactor import NacosConfigParseError, redact_nacos_config


def test_redacts_yaml_values_and_preserves_hierarchy() -> None:
    source = """
kafka:
  bootstrap-servers: 10.0.0.1:9092

  producer:
    retries: 3
  consumers:
    - group-id: message
      enabled: true
"""
    result = redact_nacos_config(source, "yaml")

    assert result["format"] == "yaml"
    assert result["key_count"] == 7
    assert "10.0.0.1" not in result["structure"]
    assert "message" not in result["structure"]
    assert "bootstrap-servers:" in result["structure"]
    assert "group-id:" in result["structure"]
    assert "null" not in result["structure"]
    assert len(result["structure"].splitlines()) == len(source.rstrip().splitlines())
    assert result["structure"].splitlines()[3] == ""
    assert "    - group-id:" in result["structure"]


def test_redacts_yaml_comments_without_reformatting_indentation() -> None:
    source = """mysql:
    host: db.internal  # password is secret
    credentials:
        - username: admin
          password: quoted-secret
"""

    result = redact_nacos_config(source, "yml")

    assert "db.internal" not in result["structure"]
    assert "password is secret" not in result["structure"]
    assert "quoted-secret" not in result["structure"]
    assert "    host:" in result["structure"]
    assert "        - username:" in result["structure"]
    assert "          password:" in result["structure"]


def test_redacts_json_values_with_valid_null_placeholders() -> None:
    result = redact_nacos_config(
        '{"database":{"host":"db.internal","ports":[3306,3307]}}',
        "json",
    )

    rendered = json.loads(result["structure"])
    assert rendered == {"database": {"host": None, "ports": [None, None]}}
    assert "db.internal" not in result["structure"]
    assert "3306" not in result["structure"]
    assert result["key_count"] == 3


@pytest.mark.parametrize("config_type", ["properties", "toml", "text"])
def test_rejects_unsupported_config_types(config_type: str) -> None:
    with pytest.raises(NacosConfigParseError, match="仅支持"):
        redact_nacos_config("key=value", config_type)


def test_parse_errors_never_include_source_content() -> None:
    secret = "do-not-return-this-secret"
    with pytest.raises(NacosConfigParseError) as error:
        redact_nacos_config(f'{{"password":"{secret}"', "json")

    assert secret not in str(error.value)
