"""Numbered, value-free previews and exact scalar selection from Nacos documents."""

import hashlib
import hmac
import json
import re
from bisect import bisect_right
from dataclasses import dataclass

import yaml
from yaml.events import AliasEvent
from yaml.nodes import MappingNode, ScalarNode, SequenceNode

from .middleware_crypto import _encryption_key
from .nacos_config_redactor import MAX_CONFIG_CONTENT_BYTES, NacosConfigParseError

SELECTION_FIELDS = ("line_number", "config_path", "source_line", "source_end_line")


def parse_line_ranges(expression: str) -> list[int]:
    numbers = set()
    if len(expression) > 2000:
        raise NacosConfigParseError("行号输入过长")
    for part in expression.replace("，", ",").split(","):
        match = re.fullmatch(r"\s*([1-9][0-9]{0,4})\s*(?:-\s*([1-9][0-9]{0,4})\s*)?", part)
        if not match:
            raise NacosConfigParseError("行号格式错误，例如 18-26，36-57；区间用 -，多个区间用逗号分隔")
        start = int(match[1])
        end = int(match[2] or match[1])
        if start > end or end > 40000:
            raise NacosConfigParseError("行号须在 1 至 40000 之间，区间起始行不能大于结束行")
        numbers.update(range(start, end + 1))
    return sorted(numbers)


def selection_metadata(selected: list[dict]) -> list[dict]:
    return [{key: item[key] for key in SELECTION_FIELDS} for item in selected]


def verify_selections(document, target):
    if not hmac.compare_digest(document.revision, target["config_revision"]):
        raise NacosConfigParseError("配置已变更，请重新获取带行号的结构并提交申请")
    numbers = parse_line_ranges(target["line_ranges"])
    if numbers[-1] > len(document.structure.splitlines()):
        raise NacosConfigParseError("行号超出当前页面结构配置的范围")
    # Collection headers are not grants to their descendants; only explicit scalar rows qualify.
    selected = [document.selections[number] for number in numbers if number in document.selections]
    if not selected:
        raise NacosConfigParseError("所选行号不包含独立配置值，请选择配置值所在的结构行号")
    if "selections" in target and selection_metadata(selected) != target["selections"]:
        raise NacosConfigParseError("配置行号与路径不匹配，请重新申请")
    return selected


def selection_scope(instance_id, namespace_id, group, data_id, config_type):
    return [instance_id, namespace_id or "public", group, data_id, "json" if config_type.strip().lower() == "json" else "yaml"]


@dataclass
class ConfigDocument:
    format: str
    structure: str
    revision: str
    key_count: int
    selections: dict[int, dict]
    source: str
    scalar_ranges: dict[int, tuple[int,int]]
    key_ranges: list[tuple[int,int]]

    def public(self):
        return {
            "format": self.format,
            "structure": self.structure,
            "config_revision": self.revision,
            "key_count": self.key_count,
            "line_count": len(self.structure.splitlines()),
            "selectable_lines": [
                {key: item[key] for key in ("line_number", "config_path", "source_line", "source_end_line")}
                for item in self.selections.values()
            ],
        }

    def select(self, line_number):
        if line_number not in self.selections:
            raise NacosConfigParseError("该行不是独立配置值，请选择含具体 Key 或数组元素的行")
        return self.selections[line_number]


def parse_config_document(content: str, config_type: str, scope: list) -> ConfigDocument:
    normalized_type = config_type.strip().lower()
    if normalized_type not in {"yaml", "yml", "json"}:
        raise NacosConfigParseError("当前仅支持 YAML、YML 和 JSON")
    if not content.strip() or len(content.encode("utf-8")) > MAX_CONFIG_CONTENT_BYTES:
        raise NacosConfigParseError("配置为空或超过 1 MB")
    try:
        if normalized_type == "json":
            def invalid_constant(_):
                raise ValueError("invalid JSON constant")
            json.loads(content, parse_constant=invalid_constant)
        for event in yaml.parse(content, Loader=yaml.SafeLoader):
            if isinstance(event, AliasEvent):
                raise NacosConfigParseError("配置包含 YAML 别名或合并引用，无法唯一定位数值")
        root = yaml.compose(content, Loader=yaml.SafeLoader)
    except NacosConfigParseError:
        raise
    except (yaml.YAMLError, ValueError, RecursionError):
        raise NacosConfigParseError("配置解析失败，请检查 YAML/JSON 格式") from None
    if not isinstance(root, (MappingNode, SequenceNode)):
        raise NacosConfigParseError("配置根节点必须是对象或数组")

    lines, selections, scalar_ranges, key_ranges = [], {}, {}, []
    node_count = key_count = 0
    is_json = normalized_type == "json"

    def pointer(path):
        return "/" + "/".join(str(part).replace("~", "~0").replace("/", "~1") for part in path) if path else ""

    def scalar(node, path, line, source_line):
        # YAML node marks refer to the original text, even for block and quoted scalars.
        if is_json:
            value = json.loads(content[node.start_mark.index:node.end_mark.index])
            value = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        else:
            value = "null" if node.tag == "tag:yaml.org,2002:null" else node.value
        selections[line] = {
            "line_number": line, "config_path": pointer(path),
            "source_line": source_line,
            "source_end_line": max(source_line, node.end_mark.line + (1 if node.end_mark.column else 0)),
            "value": value,
        }
        scalar_ranges[line]=(node.start_mark.index,node.end_mark.index)

    def walk(node, path, depth, prefix="", suffix="", source_line=1):
        nonlocal node_count, key_count
        node_count += 1
        if depth > 64 or node_count > 20000:
            raise NacosConfigParseError("配置嵌套过深或节点过多")
        indent = "  " * depth
        if isinstance(node, ScalarNode):
            lines.append(indent + prefix + "null" + suffix)
            scalar(node, path, len(lines), source_line)
            return
        if not isinstance(node, (MappingNode, SequenceNode)):
            raise NacosConfigParseError("不支持该配置节点")
        mapping = isinstance(node, MappingNode)
        children = []
        if mapping:
            seen = set()
            for key, value in node.value:
                if not isinstance(key, ScalarNode) or key.tag == "tag:yaml.org,2002:merge":
                    raise NacosConfigParseError("不支持复杂 Key 或 YAML 合并引用")
                key_value = json.loads(content[key.start_mark.index:key.end_mark.index]) if is_json else key.value
                if key_value in seen:
                    raise NacosConfigParseError("配置包含重复 Key，无法唯一定位数值")
                seen.add(key_value)
                key_ranges.append((key.start_mark.index,key.end_mark.index))
                children.append((key_value, value, key.start_mark.line + 1))
            key_count += len(children)
        else:
            children = [(index, value, value.start_mark.line + 1) for index, value in enumerate(node.value)]
        opening, closing = ("{", "}") if mapping else ("[", "]")
        if is_json:
            if not children:
                lines.append(indent + prefix + opening + closing + suffix)
                return
            lines.append(indent + prefix + opening)
            for index, (key, value, original_line) in enumerate(children):
                child_prefix = json.dumps(key, ensure_ascii=False) + ": " if mapping else ""
                walk(value, [*path, key], depth + 1, child_prefix, "," if index < len(children) - 1 else "", original_line)
            lines.append(indent + closing + suffix)
        else:
            if not children:
                lines.append(indent + prefix + opening + closing)
                return
            if prefix:
                lines.append(indent + prefix.rstrip())
                depth += 1
            for key, value, original_line in children:
                key_label = key if isinstance(key, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]*", key) else json.dumps(key, ensure_ascii=False)
                walk(value, [*path, key], depth, key_label + ": " if mapping else "- ", source_line=original_line)

    try:
        walk(root, [], 0)
    except (ValueError, RecursionError) as exc:
        if isinstance(exc, NacosConfigParseError):
            raise
        raise NacosConfigParseError("配置无法安全映射到独立数值") from None
    signed_content = json.dumps(scope, ensure_ascii=False).encode() + b"\0" + content.encode("utf-8")
    revision = hmac.new(_encryption_key(), b"nacos-line-selection:v1\0" + signed_content, hashlib.sha256).hexdigest()
    return ConfigDocument("json" if is_json else "yaml", "\n".join(lines), revision, key_count, selections,content,scalar_ranges,key_ranges)


def configuration_snapshot(document,selected):
    from yaml.tokens import ScalarToken, TagToken, AnchorToken, DirectiveToken
    granted=[document.scalar_ranges[item['line_number']] for item in selected]
    visible_ranges=sorted(document.key_ranges+granted)
    starts=[start for start,_ in visible_ranges]
    output=[];offset=0
    def whitespace(text):return ''.join(char if char.isspace() else ' ' for char in text)
    for token in yaml.scan(document.source,Loader=yaml.SafeLoader):
        start,end=token.start_mark.index,token.end_mark.index
        if end<=start:continue
        output.append(whitespace(document.source[offset:start]))
        text=document.source[start:end]
        if isinstance(token,ScalarToken):
            index=bisect_right(starts,start)-1
            visible=index>=0 and end<=visible_ranges[index][1]
            if visible and token.style in ('|','>'):
                header,separator,rest=text.partition('\n')
                if '#' in header:header=header[:header.index('#')]+whitespace(header[header.index('#'):])
                text=header+separator+rest
            output.append(text if visible else 'null'+''.join(char for char in text if char in '\r\n'))
        elif isinstance(token,(TagToken,AnchorToken,DirectiveToken)):
            output.append(whitespace(text))
        else:output.append(text)
        offset=end
    output.append(whitespace(document.source[offset:]))
    content=''.join(output)
    approved_lines=sorted({line for item in selected for line in range(item['source_line'],item['source_end_line']+1)})
    return {'format':document.format,'content':content,'line_numbers':'source','approved_lines':approved_lines,'historical_reconstruction':False}


def configuration_signature(configuration,target):
    encoded=json.dumps([target,configuration],ensure_ascii=False,sort_keys=True).encode()
    return hmac.new(_encryption_key(),b'nacos-configuration-snapshot:v1\0'+encoded,hashlib.sha256).hexdigest()


def historical_configuration(values):
    # Older snapshots contain paths and selected values only, never consult today's live source.
    tree={}
    for item in values:
        parts=[part.replace('~1','/').replace('~0','~') for part in item['config_path'].split('/')[1:]]
        cursor=tree
        for part in parts[:-1]:cursor=cursor.setdefault(part,{})
        if parts:cursor[parts[-1]]=item['value']
    return {'format':'yaml','content':yaml.safe_dump(tree,allow_unicode=True,sort_keys=False),
        'line_numbers':'display','approved_lines':[],'historical_reconstruction':True}


def verify_selection(document: ConfigDocument, target: dict):
    if not hmac.compare_digest(document.revision, target["config_revision"]):
        raise NacosConfigParseError("配置已变更，请重新获取带行号的结构并提交申请")
    selected = document.select(target["line_number"])
    if "config_path" in target and (
        selected["config_path"] != target["config_path"]
        or selected["source_line"] != target["source_line"]
        or selected["source_end_line"] != target["source_end_line"]
    ):
        raise NacosConfigParseError("配置行号与路径不匹配，请重新申请")
    return selected
