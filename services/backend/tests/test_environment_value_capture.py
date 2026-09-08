from contextlib import nullcontext
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest

from app import k8s_client as k8s


@pytest.fixture
def exec_source(monkeypatch):
    owner = NS(kind="StatefulSet", name="app", controller=True)
    selected = NS(metadata=NS(name="app-0", uid="pod-uid", owner_references=[owner]),
        spec=NS(containers=[NS(name="app"), NS(name="sidecar")]),
        status=NS(phase="Running", container_statuses=[NS(ready=True)]))
    unrelated = NS(metadata=NS(name="unrelated-0", owner_references=[NS(kind="StatefulSet", name="other", controller=True)]))
    apps = Mock()
    apps.read_namespaced_stateful_set.return_value = NS(spec=NS(selector=NS(match_labels={"app":"example"}, match_expressions=[])))
    core = Mock()
    core.list_namespaced_pod.return_value = NS(items=[unrelated, selected])
    socket = Mock()
    socket.is_open.return_value = False
    socket.returncode = 0
    socket.read_stdout.return_value = " first=line\nsecond=line\n\n"
    stream = Mock(return_value=socket)
    monkeypatch.setattr(k8s, "_api_client", lambda _: nullcontext(object()))
    monkeypatch.setattr(k8s.client, "AppsV1Api", lambda _: apps)
    monkeypatch.setattr(k8s.client, "CoreV1Api", lambda _: core)
    monkeypatch.setattr(k8s, "stream", stream)
    return socket, stream


def test_reads_only_requested_container_key_and_preserves_multiline_value(exec_source):
    _, stream = exec_source
    result = k8s.get_workload_environment_keys({}, "test", "StatefulSet", "app", value_container="app", value_key="TEST_KEY")
    assert result["value"] == " first=line\nsecond=line\n"
    assert result["pod_name"] == "app-0"
    assert result["pod_uid"] == "pod-uid"
    assert stream.call_count == 1
    assert stream.call_args.kwargs["container"] == "app"
    assert stream.call_args.kwargs["command"][-1] == "TEST_KEY"


def test_missing_key_is_error_and_empty_value_is_distinct(exec_source):
    socket, _ = exec_source
    socket.read_stdout.return_value = "\n"
    assert k8s.get_workload_environment_keys({}, "test", "StatefulSet", "app", value_container="app", value_key="EMPTY")["value"] == ""
    socket.returncode = 1
    with pytest.raises(k8s.K8sIntegrationError):
        k8s.get_workload_environment_keys({}, "test", "StatefulSet", "app", value_container="app", value_key="MISSING")


def test_rejects_shell_injection_and_missing_container(exec_source):
    _, stream = exec_source
    with pytest.raises(k8s.K8sIntegrationError):
        k8s.get_workload_environment_keys({}, "test", "StatefulSet", "app", value_container="app", value_key="X;cat /etc/passwd")
    with pytest.raises(k8s.K8sIntegrationError):
        k8s.get_workload_environment_keys({}, "test", "StatefulSet", "app", value_container="missing", value_key="X")
    stream.assert_not_called()


def test_existing_key_listing_remains_redacted(exec_source):
    socket, stream = exec_source
    socket.read_stdout.return_value = "ONE\nTWO\n"
    result = k8s.get_workload_environment_keys({}, "test", "StatefulSet", "app")
    assert [item["keys"] for item in result["containers"]] == [["ONE", "TWO"], ["ONE", "TWO"]]
    assert all("value" not in item for item in result["containers"])
    assert "/proc/self/environ" in stream.call_args.kwargs["command"][-1]
