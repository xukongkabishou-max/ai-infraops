import json
from typing import Any

import yaml
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode


MAX_CONFIG_CONTENT_BYTES = 1_000_000
SUPPORTED_CONFIG_TYPES = {"json", "yaml", "yml"}


class NacosConfigParseError(ValueError):
    pass


def redact_nacos_config(content: str, config_type: str) -> dict:
    normalized_type = config_type.strip().lower()
    if normalized_type not in SUPPORTED_CONFIG_TYPES:
        raise NacosConfigParseError("当前仅支持解析 YAML、YML 和 JSON 配置")
    if not content.strip():
        raise NacosConfigParseError("配置正文为空")
    if len(content.encode("utf-8")) > MAX_CONFIG_CONTENT_BYTES:
        raise NacosConfigParseError("配置正文超过 1 MB，暂不支持在线解析")

    if normalized_type == "json":
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise NacosConfigParseError("JSON 配置无法解析") from exc
        if not isinstance(parsed, (dict, list)):
            raise NacosConfigParseError("配置根节点必须是对象或数组")
        redacted = _redact_values(parsed)
        rendered = json.dumps(redacted, ensure_ascii=False, indent=2)
        key_count = _count_keys(redacted)
    else:
        rendered, key_count = _redact_yaml_preserving_layout(content)

    return {
        "format": "yaml" if normalized_type in {"yaml", "yml"} else "json",
        "key_count": key_count,
        "structure": rendered,
    }


def _redact_yaml_preserving_layout(content: str) -> tuple[str, int]:
    try:
        root = yaml.compose(content, Loader=yaml.SafeLoader)
    except yaml.YAMLError as exc:
        raise NacosConfigParseError("YAML 配置无法解析") from exc
    if root is None:
        raise NacosConfigParseError("配置正文为空")
    if not isinstance(root, (MappingNode, SequenceNode)):
        raise NacosConfigParseError("配置根节点必须是对象或数组")

    value_ranges: list[tuple[int, int]] = []
    key_count = _collect_yaml_value_ranges(root, value_ranges, set())
    redacted = list(content)
    for start, end in value_ranges:
        for index in range(start, end):
            if redacted[index] not in {"\r", "\n"}:
                redacted[index] = " "
    _redact_yaml_comments(redacted)
    return "".join(redacted).rstrip("\r\n"), key_count


def _collect_yaml_value_ranges(
    node: Node,
    value_ranges: list[tuple[int, int]],
    visited: set[int],
) -> int:
    node_id = id(node)
    if node_id in visited:
        return 0
    visited.add(node_id)

    if isinstance(node, MappingNode):
        return len(node.value) + sum(
            _collect_yaml_value_ranges(value_node, value_ranges, visited)
            for _key_node, value_node in node.value
        )
    if isinstance(node, SequenceNode):
        return sum(
            _collect_yaml_value_ranges(child, value_ranges, visited)
            for child in node.value
        )
    if isinstance(node, ScalarNode):
        value_ranges.append((node.start_mark.index, node.end_mark.index))
    return 0


def _redact_yaml_comments(content: list[str]) -> None:
    line_start = 0
    while line_start < len(content):
        line_end = line_start
        while line_end < len(content) and content[line_end] not in {"\r", "\n"}:
            line_end += 1
        _redact_yaml_line_comment(content, line_start, line_end)
        line_start = line_end + 1
        if line_end < len(content) and content[line_end] == "\r":
            line_start += 1


def _redact_yaml_line_comment(content: list[str], start: int, end: int) -> None:
    in_single_quote = False
    in_double_quote = False
    index = start
    while index < end:
        character = content[index]
        if in_double_quote and character == "\\":
            index += 2
            continue
        if not in_double_quote and character == "'":
            if in_single_quote and index + 1 < end and content[index + 1] == "'":
                index += 2
                continue
            in_single_quote = not in_single_quote
        elif not in_single_quote and character == '"':
            in_double_quote = not in_double_quote
        elif (
            not in_single_quote
            and not in_double_quote
            and character == "#"
            and (index == start or content[index - 1].isspace())
        ):
            for comment_index in range(index, end):
                content[comment_index] = " "
            return
        index += 1


def _redact_values(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _redact_values(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_redact_values(child) for child in value]
    return None


def _count_keys(value: Any) -> int:
    if isinstance(value, dict):
        return len(value) + sum(_count_keys(child) for child in value.values())
    if isinstance(value, list):
        return sum(_count_keys(child) for child in value)
    return 0
