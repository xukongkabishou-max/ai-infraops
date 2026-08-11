from contextlib import contextmanager
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from app import k8s_client


def _service(name: str, service_type: str, ports: list[SimpleNamespace]) -> SimpleNamespace:
    return SimpleNamespace(
        metadata=SimpleNamespace(name=name, namespace="observe", labels={}),
        spec=SimpleNamespace(type=service_type, ports=ports, cluster_ip="10.0.0.1"),
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


class NodeResourceTests(TestCase):
    def test_requests_structured_prometheus_response(self) -> None:
        api_client = Mock()
        api_client.call_api.return_value = {
            "status": "success",
            "data": {"result": []},
        }

        result = k8s_client._prometheus_query(
            api_client,
            {
                "scheme": "http",
                "namespace": "monitoring",
                "service_name": "prometheus-server",
                "port": "http-web",
            },
            "node_uname_info",
        )

        self.assertEqual(result, [])
        self.assertEqual(
            api_client.call_api.call_args.kwargs["response_types_map"],
            {200: "object"},
        )

    def test_parses_prometheus_service_proxy_byte_response(self) -> None:
        class FakeApiClient:
            def call_api(self, *_args, **_kwargs):
                return b'{"status":"success","data":{"result":[{"metric":{"instance":"node:9100"},"value":[0,"1"]}]}}'

        result = k8s_client._prometheus_query(
            FakeApiClient(),
            {
                "scheme": "http",
                "namespace": "monitoring",
                "service_name": "prometheus-server",
                "port": "http-web",
            },
            "node_uname_info",
        )

        self.assertEqual(result[0]["metric"]["instance"], "node:9100")

    def test_collects_multiple_k8s_nodes_from_prometheus(self) -> None:
        nodes = [
            self._node("worker-a", "10.0.0.11"),
            self._node("worker-b", "10.0.0.12"),
        ]
        prometheus_service = _service(
            "kube-prom-stack-prometheus",
            "ClusterIP",
            [SimpleNamespace(name="http-web", protocol="TCP", port=9090)],
        )

        class FakeCoreV1Api:
            def __init__(self, _api_client: object) -> None:
                pass

            def list_node(self, **_kwargs: object) -> SimpleNamespace:
                return SimpleNamespace(items=nodes)

            def list_service_for_all_namespaces(self, **_kwargs: object) -> SimpleNamespace:
                return SimpleNamespace(items=[prometheus_service])

        @contextmanager
        def fake_api_client(_cluster: dict):
            yield object()

        vectors = self._vectors()
        with (
            patch.object(k8s_client, "_api_client", fake_api_client),
            patch.object(k8s_client.client, "CoreV1Api", FakeCoreV1Api),
            patch.object(
                k8s_client,
                "_prometheus_query",
                side_effect=lambda _client, _service, query: vectors[query],
            ),
        ):
            result = k8s_client.get_cluster_node_resources({})

        self.assertEqual(len(result["nodes"]), 2)
        first = result["nodes"][0]
        self.assertEqual(first["name"], "worker-a")
        self.assertTrue(first["ready"])
        self.assertTrue(first["metrics_available"])
        self.assertEqual(first["cpu"]["coreCount"], 8)
        self.assertEqual(first["cpu"]["usagePercent"], 12.5)
        self.assertEqual(first["memory"]["usagePercent"], 50.0)
        self.assertEqual(first["rootDisk"]["availableBytes"], 75)

    def test_keeps_single_node_cluster_as_one_node(self) -> None:
        nodes = [self._node("single", "10.0.0.21")]
        result = k8s_client._merge_node_resources(
            nodes,
            {
                "uname": [self._sample("10.0.0.21:9100", 1, nodename="single")],
                "cpu_usage": [self._sample("10.0.0.21:9100", 2)],
                "cpu_cores": [self._sample("10.0.0.21:9100", 4)],
                "memory_total": [self._sample("10.0.0.21:9100", 100)],
                "memory_available": [self._sample("10.0.0.21:9100", 60)],
                "root_size": [self._sample("10.0.0.21:9100", 200)],
                "root_available": [self._sample("10.0.0.21:9100", 150)],
            },
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "single")
        self.assertEqual(result[0]["cpu"]["coreCount"], 4)

    def test_marks_node_when_prometheus_has_no_exporter_series(self) -> None:
        result = k8s_client._merge_node_resources(
            [self._node("missing", "10.0.0.31")],
            {key: [] for key in k8s_client.PROMETHEUS_NODE_QUERIES},
        )

        self.assertFalse(result[0]["metrics_available"])
        self.assertIn("尚未采集", result[0]["metrics_error"])

    def test_single_node_can_fall_back_to_direct_node_exporter(self) -> None:
        node = {
            "name": "single",
            "ready": True,
            "internal_ip": "10.0.0.31",
            "external_ip": None,
            "metrics_available": False,
            "metrics_error": "missing",
            "cpu": {"coreCount": 0, "usagePercent": 0, "window": "5m"},
            "memory": {},
            "rootDisk": {},
        }
        exporter_metrics = {
            "cpu": {"coreCount": 48, "usagePercent": 12.5},
            "memory": {"usagePercent": 50.0},
            "rootDisk": {"usagePercent": 60.0},
        }

        result = k8s_client.apply_single_node_exporter_fallback(
            [node], exporter_metrics
        )

        self.assertEqual(result[0]["name"], "single")
        self.assertEqual(result[0]["internal_ip"], "10.0.0.31")
        self.assertTrue(result[0]["metrics_available"])
        self.assertIsNone(result[0]["metrics_error"])
        self.assertEqual(result[0]["cpu"]["coreCount"], 48)
        self.assertEqual(result[0]["cpu"]["window"], "sample")

    def test_multi_node_cluster_does_not_use_one_exporter_for_every_node(self) -> None:
        nodes = [
            {"name": "worker-a", "metrics_available": False},
            {"name": "worker-b", "metrics_available": False},
        ]

        result = k8s_client.apply_single_node_exporter_fallback(
            nodes,
            {"cpu": {}, "memory": {}, "rootDisk": {}},
        )

        self.assertIs(result, nodes)

    def test_fills_missing_node_metrics_from_kubelet_summary(self) -> None:
        node = self._node("worker-a", "10.0.0.31")
        node.status.capacity = {"cpu": "8", "memory": "16Gi"}
        resource = {
            "name": "worker-a",
            "ready": True,
            "internal_ip": "10.0.0.31",
            "external_ip": None,
            "metrics_available": False,
            "metrics_error": "missing",
            "cpu": {"coreCount": 0, "usagePercent": 0, "window": "5m"},
            "memory": {},
            "rootDisk": {},
        }
        api_client = Mock()
        api_client.call_api.return_value = {
            "node": {
                "cpu": {"usageNanoCores": 2_000_000_000},
                "memory": {"availableBytes": 4 * 1024**3},
                "fs": {
                    "capacityBytes": 100 * 1024**3,
                    "availableBytes": 40 * 1024**3,
                },
            }
        }

        result = k8s_client._fill_missing_nodes_from_kubelet(
            api_client, [node], [resource]
        )

        self.assertTrue(result[0]["metrics_available"])
        self.assertEqual(result[0]["cpu"]["coreCount"], 8)
        self.assertEqual(result[0]["cpu"]["usagePercent"], 25.0)
        self.assertEqual(result[0]["cpu"]["window"], "sample")
        self.assertEqual(result[0]["memory"]["usagePercent"], 75.0)
        self.assertEqual(result[0]["rootDisk"]["usagePercent"], 60.0)
        self.assertEqual(
            api_client.call_api.call_args.args[0],
            "/api/v1/nodes/worker-a/proxy/stats/summary",
        )

    @staticmethod
    def _node(name: str, internal_ip: str) -> SimpleNamespace:
        return SimpleNamespace(
            metadata=SimpleNamespace(name=name),
            status=SimpleNamespace(
                addresses=[SimpleNamespace(type="InternalIP", address=internal_ip)],
                conditions=[SimpleNamespace(type="Ready", status="True")],
            ),
        )

    @staticmethod
    def _sample(instance: str, value: float, nodename: str | None = None) -> dict:
        metric = {"instance": instance}
        if nodename:
            metric["nodename"] = nodename
        return {"metric": metric, "value": [0, str(value)]}

    def _vectors(self) -> dict[str, list[dict]]:
        instances = ["10.0.0.11:9100", "10.0.0.12:9100"]
        node_names = ["worker-a", "worker-b"]
        by_key = {
            "uname": [
                self._sample(instance, 1, nodename=node_name)
                for instance, node_name in zip(instances, node_names)
            ],
            "cpu_usage": [self._sample(instance, 12.5) for instance in instances],
            "cpu_cores": [self._sample(instance, 8) for instance in instances],
            "memory_total": [self._sample(instance, 100) for instance in instances],
            "memory_available": [self._sample(instance, 50) for instance in instances],
            "root_size": [self._sample(instance, 100) for instance in instances],
            "root_available": [self._sample(instance, 75) for instance in instances],
        }
        return {
            query: by_key[key]
            for key, query in k8s_client.PROMETHEUS_NODE_QUERIES.items()
        }
