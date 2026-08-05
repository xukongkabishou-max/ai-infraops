from contextlib import contextmanager
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from app import k8s_client


def _service(name: str, service_type: str, ports: list[SimpleNamespace]) -> SimpleNamespace:
    return SimpleNamespace(
        metadata=SimpleNamespace(name=name),
        spec=SimpleNamespace(type=service_type, ports=ports),
    )


class NodePortServiceTests(TestCase):
    def test_lists_each_nodeport_and_builds_stable_names(self) -> None:
        services = [
            _service(
                "agent-nodeport",
                "NodePort",
                [SimpleNamespace(name="tcp", protocol="TCP", port=8101, node_port=31001)],
            ),
            _service(
                "gateway-nodeport",
                "NodePort",
                [
                    SimpleNamespace(name="http", protocol="TCP", port=8080, node_port=30080),
                    SimpleNamespace(name=None, protocol="UDP", port=9090, node_port=30090),
                ],
            ),
            _service(
                "internal-only",
                "ClusterIP",
                [SimpleNamespace(name="http", protocol="TCP", port=80, node_port=None)],
            ),
        ]

        class FakeCoreV1Api:
            def __init__(self, _api_client: object) -> None:
                pass

            def list_namespaced_service(self, namespace: str, **_kwargs: object) -> SimpleNamespace:
                self.namespace = namespace
                return SimpleNamespace(items=services)

        @contextmanager
        def fake_api_client(_cluster: dict):
            yield object()

        with (
            patch.object(k8s_client, "_api_client", fake_api_client),
            patch.object(k8s_client.client, "CoreV1Api", FakeCoreV1Api),
        ):
            rows = k8s_client.list_nodeport_services({}, "dev")

        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["service_name"], "agent-nodeport")
        self.assertEqual(rows[0]["service_display_name"], "agent")
        self.assertEqual(rows[0]["port_name"], "tcp")
        gateway_ports = {row["port_name"]: row for row in rows[1:]}
        self.assertEqual(set(gateway_ports), {"http", "9090-udp"})
        self.assertEqual(gateway_ports["http"]["node_port"], 30080)
        self.assertEqual(gateway_ports["9090-udp"]["protocol"], "UDP")
