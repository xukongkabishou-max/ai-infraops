import json

import pytest

from app import nacos_value_selection as selection
from app.nacos_config_redactor import NacosConfigParseError


@pytest.fixture(autouse=True)
def key(monkeypatch):
    monkeypatch.setattr(selection, "_encryption_key", lambda: b"k" * 32)


def parse(content, config_type="yaml"):
    return selection.parse_config_document(content, config_type, selection.selection_scope(1, "test", "group", "app", config_type))


def test_comments_blank_lines_crlf_and_multiline_values_have_exact_mapping():
    source = '# hidden-comment\r\n\r\ndatabase:\r\n  password: "first-secret" # another-secret\r\n\r\n  cert: |\r\n    cert-line-one\r\n    cert-line-two\r\n  empty: ""\r\n'
    document = parse(source)
    public = document.public()
    assert document.structure == 'database:\n  password: null\n  cert: null\n  empty: null'
    assert document.select(2)["value"] == "first-secret"
    assert document.select(2)["config_path"] == "/database/password"
    assert document.select(2)["source_line"] == 4
    assert document.select(3)["value"] == "cert-line-one\ncert-line-two\n"
    assert document.select(3)["source_line"] == 6
    assert document.select(3)["source_end_line"] == 8
    assert document.select(4)["value"] == ""
    for secret in ("first-secret", "hidden-comment", "another-secret", "cert-line-one"):
        assert secret not in json.dumps(public)
    with pytest.raises(NacosConfigParseError): document.select(1)


def test_inline_yaml_arrays_nested_objects_and_pointer_escaping():
    document = parse('list: [{"a/b~c": "one-secret"}, "two-secret"]\nother: {key: three-secret}\n')
    entries = list(document.selections.values())
    assert [entry["value"] for entry in entries] == ["one-secret", "two-secret", "three-secret"]
    assert [entry["config_path"] for entry in entries] == ["/list/0/a~1b~0c", "/list/1", "/other/key"]
    assert len({entry["line_number"] for entry in entries}) == 3
    assert [entry["source_line"] for entry in entries] == [1,1,2]


def test_minified_json_pretty_preview_has_separate_line_for_every_scalar():
    source = '{"db":{"password":"one-secret","port":3306},"array":[false,null,"two-secret"]}'
    document = parse(source, "json")
    assert json.loads(document.structure) == {"db":{"password":None,"port":None},"array":[None,None,None]}
    entries = list(document.selections.values())
    assert [entry["value"] for entry in entries] == ["one-secret","3306","false","null","two-secret"]
    assert all(entry["source_line"] == 1 for entry in entries)
    assert len({entry["line_number"] for entry in entries}) == 5
    assert "one-secret" not in json.dumps(document.public())


def test_multiline_json_key_and_value_original_lines():
    document = parse('{\n  "key":\n    "escaped\\nsecret",\n  "empty": ""\n}', "json")
    assert document.select(2)["source_line"] == 2
    assert document.select(2)["source_end_line"] == 3
    assert document.select(2)["value"] == "escaped\nsecret"


@pytest.mark.parametrize("content,kind", [
    ('a: secret\na: another', 'yaml'),
    ('{"a":1,"a":2}', 'json'),
    ('base: &base {password: secret}\ncopy: *base', 'yaml'),
    ('a: &a [*a]', 'yaml'),
    ('? [a,b]\n: secret', 'yaml'),
    ('{"a":NaN}', 'json'),
    ('{"password":"top-secret"', 'json'),
])
def test_rejects_ambiguous_or_invalid_documents_without_leaking(content, kind):
    with pytest.raises(NacosConfigParseError) as error: parse(content, kind)
    assert "secret" not in str(error.value)


def test_version_binds_raw_content_and_instance_scope():
    document = parse('a: secret\n')
    target = {"line_number":1,"config_revision":document.revision,**document.select(1)}
    assert selection.verify_selection(document,target)["value"] == "secret"
    with pytest.raises(NacosConfigParseError): selection.verify_selection(parse('# comment\na: secret\n'),target)
    other = selection.parse_config_document('a: secret\n', 'yaml', [2,'test','group','app','yaml'])
    assert other.revision != document.revision
    with pytest.raises(NacosConfigParseError): selection.verify_selection(document,{**target,"config_path":"/another"})


def test_empty_collections_and_implicit_nulls_cannot_expand_authorization():
    document = parse('empty_map: {}\nempty_list: []\nmissing:\nnext: secret\n')
    with pytest.raises(NacosConfigParseError): document.select(1)
    with pytest.raises(NacosConfigParseError): document.select(2)
    assert document.select(3)["value"] == "null"
    assert document.select(3)["source_line"] == 3
    assert document.select(4)["value"] == "secret"


def test_json_escaped_unicode_keys_are_matched_by_decoded_identity():
    document = parse(r'{"\uD83D\uDE00":"secret"}', 'json')
    assert document.select(2)["config_path"] == "/\U0001f600"
    assert document.public()["structure"].encode('utf-8')
    with pytest.raises(NacosConfigParseError):
        parse(r'{"\uD83D\uDE00":1,"\ud83d\ude00":2}', 'json')


def test_default_namespace_aliases_use_the_same_revision_scope():
    empty_scope = selection.selection_scope(1, "", "group", "app", "yaml")
    public_scope = selection.selection_scope(1, "public", "group", "app", "yml")
    assert empty_scope == public_scope
    assert selection.parse_config_document('key: secret', 'yaml', empty_scope).revision == selection.parse_config_document('key: secret', 'yml', public_scope).revision


def test_range_parser_accepts_chinese_commas_mixed_rows_and_deduplicates():
    assert selection.parse_line_ranges("18-26，36-57") == list(range(18,27)) + list(range(36,58))
    assert selection.parse_line_ranges(" 2-4, 3，7, 9 - 10 ") == [2,3,4,7,9,10]


@pytest.mark.parametrize("expression", ["", "1~13", "1;13", "1,,13", "13,", "0", "-1", "1.5", "1e3", "26-18", "40001", "1-999999999", "١"])
def test_range_parser_rejects_ambiguous_or_unbounded_input(expression):
    with pytest.raises(NacosConfigParseError):
        selection.parse_line_ranges(expression)


@pytest.mark.parametrize("source,kind,expression,expected", [
    ('# hidden comment\r\n\r\nroot:\r\n  a: first\r\n\r\n  block: |\r\n    second\r\n    third\r\n  omitted: private\r\n  last: last\r\n', 'yaml', '1-3，5', [(2,'/root/a',4,4,'first'),(3,'/root/block',6,8,'second\nthird\n'),(5,'/root/last',10,10,'last')]),
    ('{"root":{"a":"first","b":"private"},"list":["last"]}', 'json', '1-3，7-9', [(3,'/root/a',1,1,'first'),(7,'/list/0',1,1,'last')]),
])
def test_ranges_bind_display_path_and_original_marks_without_neighbor_values(source, kind, expression, expected):
    document = parse(source, kind)
    target = {"line_ranges":expression,"config_revision":document.revision}
    items = selection.verify_selections(document, target)
    assert [tuple(item[key] for key in (*selection.SELECTION_FIELDS, 'value')) for item in items] == expected
    assert 'private' not in json.dumps(items)
    target['selections'] = selection.selection_metadata(items)
    assert selection.verify_selections(document, target) == items
    target['selections'][0]['source_line'] += 1
    with pytest.raises(NacosConfigParseError): selection.verify_selections(document, target)


def test_collection_header_does_not_grant_descendants_and_out_of_bounds_fails():
    document = parse('root:\n  a: secret\n  b: hidden\n')
    for expression in ('1', '1-4'):
        with pytest.raises(NacosConfigParseError):
            selection.verify_selections(document, {'line_ranges':expression,'config_revision':document.revision})
    target = {'line_ranges':'1-2','config_revision':document.revision}
    assert [item['value'] for item in selection.verify_selections(document,target)] == ['secret']
    with pytest.raises(NacosConfigParseError):
        selection.verify_selections(parse('# new comment\nroot:\n  a: secret\n  b: hidden\n'),target)


def test_configuration_snapshot_preserves_source_layout_only_reveals_selected_scalars():
    source='# hidden-comment\n\nconsumer:\n  group-id: ${spring.application.name:ecmas-server}\n  auto-offset-reset: latest\n  private: super-secret # secret-comment\n'
    doc=parse(source)
    result=selection.configuration_snapshot(doc,[doc.select(2),doc.select(3)])
    assert '  group-id: ${spring.application.name:ecmas-server}\n  auto-offset-reset: latest\n' in result['content']
    assert '  private: null' in result['content']
    assert all(secret not in result['content'] for secret in ('hidden-comment','super-secret','secret-comment'))
    assert result['approved_lines']==[4,5]
    assert len(result['content'].splitlines())==len(source.splitlines())


def test_configuration_snapshot_blocks_and_json_are_safe_and_valid():
    import yaml
    doc=parse('root:\n  block: | # private-header\n    line one\n    line two\n  hidden: |\n    must-not-leak\n')
    result=selection.configuration_snapshot(doc,[doc.select(2)])
    assert yaml.safe_load(result['content'])=={'root':{'block':'line one\nline two\n','hidden':None}}
    assert 'private-header' not in result['content'] and 'must-not-leak' not in result['content']
    doc=parse('{"approved":true,"hidden":"secret"}','json')
    result=selection.configuration_snapshot(doc,[doc.select(2)])
    assert json.loads(result['content'])=={'approved':True,'hidden':None}
