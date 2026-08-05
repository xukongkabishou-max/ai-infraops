from cryptography.exceptions import InvalidTag
from kubernetes import client, config
from kubernetes.client.exceptions import ApiException
from kubernetes.config.config_exception import ConfigException
from kubernetes.stream import stream
from urllib3.exceptions import HTTPError as Urllib3HTTPError
from websocket import WebSocketException
import yaml

from .config import settings
from .credential_crypto import CredentialConfigurationError, decrypt_credential


class K8sIntegrationError(RuntimeError):
    pass


def list_namespaces(cluster: dict) -> list[str]:
    try:
        with _api_client(cluster) as api_client:
            response = client.CoreV1Api(api_client).list_namespace(
                _request_timeout=_request_timeout(),
            )
    except (
        ApiException,
        ConfigException,
        CredentialConfigurationError,
        InvalidTag,
        OSError,
        Urllib3HTTPError,
        ValueError,
        yaml.YAMLError,
    ) as exc:
        raise K8sIntegrationError(_safe_error(exc)) from exc

    return sorted(
        item.metadata.name
        for item in response.items
        if item.metadata and item.metadata.name
    )


def list_nodeport_services(cluster: dict, namespace: str) -> list[dict]:
    try:
        with _api_client(cluster) as api_client:
            services = client.CoreV1Api(api_client).list_namespaced_service(
                namespace,
                _request_timeout=_request_timeout(),
            ).items
    except _K8S_ERRORS as exc:
        raise K8sIntegrationError(_safe_error(exc)) from exc

    result = []
    for service in services:
        if not service.metadata or not service.metadata.name or not service.spec:
            continue
        if service.spec.type != "NodePort":
            continue

        service_name = service.metadata.name
        display_name = service_name.removesuffix("-nodeport") or service_name
        for port in service.spec.ports or []:
            if port.node_port is None:
                continue
            protocol = (port.protocol or "TCP").upper()
            result.append(
                {
                    "service_name": service_name,
                    "service_display_name": display_name,
                    "port_name": port.name or f"{port.port}-{protocol.lower()}",
                    "protocol": protocol,
                    "service_port": port.port,
                    "node_port": port.node_port,
                }
            )

    return sorted(
        result,
        key=lambda row: (row["service_display_name"], row["port_name"], row["node_port"]),
    )


def list_running_controller_images(cluster: dict, namespace: str) -> list[dict]:
    try:
        with _api_client(cluster) as api_client:
            pods = client.CoreV1Api(api_client).list_namespaced_pod(
                namespace,
                _request_timeout=_request_timeout(),
            ).items
            apps_api = client.AppsV1Api(api_client)
            replica_sets = apps_api.list_namespaced_replica_set(
                namespace,
                _request_timeout=_request_timeout(),
            ).items
            deployments = apps_api.list_namespaced_deployment(
                namespace,
                _request_timeout=_request_timeout(),
            ).items
            stateful_sets = apps_api.list_namespaced_stateful_set(
                namespace,
                _request_timeout=_request_timeout(),
            ).items
            daemon_sets = apps_api.list_namespaced_daemon_set(
                namespace,
                _request_timeout=_request_timeout(),
            ).items
    except (
        ApiException,
        ConfigException,
        CredentialConfigurationError,
        InvalidTag,
        OSError,
        Urllib3HTTPError,
        ValueError,
        yaml.YAMLError,
    ) as exc:
        raise K8sIntegrationError(_safe_error(exc)) from exc

    replica_set_deployments: dict[str, str] = {}
    for replica_set in replica_sets:
        owner = _controller_owner(replica_set.metadata.owner_references if replica_set.metadata else None)
        if owner and owner.kind == "Deployment" and replica_set.metadata.name:
            replica_set_deployments[replica_set.metadata.name] = owner.name

    controller_replicas: dict[tuple[str, str], tuple[int, int]] = {}
    for deployment in deployments:
        if deployment.metadata and deployment.metadata.name:
            controller_replicas[("Deployment", deployment.metadata.name)] = (
                deployment.status.ready_replicas or 0,
                deployment.spec.replicas or 0,
            )
    for stateful_set in stateful_sets:
        if stateful_set.metadata and stateful_set.metadata.name:
            controller_replicas[("StatefulSet", stateful_set.metadata.name)] = (
                stateful_set.status.ready_replicas or 0,
                stateful_set.spec.replicas or 0,
            )
    for daemon_set in daemon_sets:
        if daemon_set.metadata and daemon_set.metadata.name:
            controller_replicas[("DaemonSet", daemon_set.metadata.name)] = (
                daemon_set.status.number_ready or 0,
                daemon_set.status.desired_number_scheduled or 0,
            )

    controller_rows: dict[tuple[str, str], dict] = {}
    for pod in pods:
        if not pod.metadata or not pod.status or pod.status.phase != "Running":
            continue
        owner = _controller_owner(pod.metadata.owner_references)
        if not owner:
            continue
        if owner.kind == "ReplicaSet" and owner.name in replica_set_deployments:
            controller_type = "Deployment"
            controller_name = replica_set_deployments[owner.name]
        elif owner.kind in {"StatefulSet", "DaemonSet"}:
            controller_type = owner.kind
            controller_name = owner.name
        else:
            continue

        running_containers = [
            status
            for status in pod.status.container_statuses or []
            if status.state and status.state.running
        ]
        if not running_containers:
            continue

        key = (controller_type, controller_name)
        if key not in controller_rows:
            controller_rows[key] = {
                "controller_type": controller_type,
                "pods": {},
            }
        row = controller_rows[key]
        row["pods"][pod.metadata.name] = [
            {"name": status.name, "image": status.image or ""}
            for status in sorted(running_containers, key=lambda item: item.name)
        ]

    result = []
    for (controller_type, controller_name), row in controller_rows.items():
        ready_replicas, desired_replicas = controller_replicas.get(
            (controller_type, controller_name),
            (len(row["pods"]), len(row["pods"])),
        )
        for pod_name, containers in sorted(row["pods"].items()):
            result.append(
                {
                    "controller_type": controller_type,
                    "controller_name": controller_name,
                    "pod_name": pod_name,
                    "ready_replicas": ready_replicas,
                    "desired_replicas": desired_replicas,
                    "containers": containers,
                }
            )
    return sorted(result, key=lambda row: (row["controller_type"], row["pod_name"]))


def list_env_workloads(cluster: dict, namespace: str) -> list[dict]:
    try:
        with _api_client(cluster) as api_client:
            apps_api = client.AppsV1Api(api_client)
            deployments = apps_api.list_namespaced_deployment(
                namespace,
                _request_timeout=_request_timeout(),
            ).items
            stateful_sets = apps_api.list_namespaced_stateful_set(
                namespace,
                _request_timeout=_request_timeout(),
            ).items
    except _K8S_ERRORS as exc:
        raise K8sIntegrationError(_safe_error(exc)) from exc

    workloads = []
    for kind, items in (("Deployment", deployments), ("StatefulSet", stateful_sets)):
        for item in items:
            if not item.metadata or not item.metadata.name:
                continue
            workloads.append(
                {
                    "kind": kind,
                    "name": item.metadata.name,
                    "ready_replicas": item.status.ready_replicas or 0,
                    "desired_replicas": item.spec.replicas or 0,
                }
            )
    return sorted(workloads, key=lambda item: (item["kind"], item["name"]))


def get_workload_environment_keys(
    cluster: dict,
    namespace: str,
    kind: str,
    workload_name: str,
) -> dict:
    normalized_kind = kind.strip().lower()
    if normalized_kind not in {"deployment", "statefulset"}:
        raise K8sIntegrationError("仅支持 Deployment 和 StatefulSet")

    try:
        with _api_client(cluster) as api_client:
            apps_api = client.AppsV1Api(api_client)
            core_api = client.CoreV1Api(api_client)
            if normalized_kind == "deployment":
                workload = apps_api.read_namespaced_deployment(
                    workload_name,
                    namespace,
                    _request_timeout=_request_timeout(),
                )
            else:
                workload = apps_api.read_namespaced_stateful_set(
                    workload_name,
                    namespace,
                    _request_timeout=_request_timeout(),
                )

            selector = _label_selector(workload.spec.selector)
            pods = core_api.list_namespaced_pod(
                namespace,
                label_selector=selector,
                _request_timeout=_request_timeout(),
            ).items

            if normalized_kind == "deployment":
                replica_sets = apps_api.list_namespaced_replica_set(
                    namespace,
                    label_selector=selector,
                    _request_timeout=_request_timeout(),
                ).items
                owned_replica_sets = {
                    item.metadata.name
                    for item in replica_sets
                    if item.metadata
                    and item.metadata.name
                    and (owner := _controller_owner(item.metadata.owner_references))
                    and owner.kind == "Deployment"
                    and owner.name == workload_name
                }
                pods = [
                    pod
                    for pod in pods
                    if (owner := _controller_owner(pod.metadata.owner_references if pod.metadata else None))
                    and owner.kind == "ReplicaSet"
                    and owner.name in owned_replica_sets
                ]
            else:
                pods = [
                    pod
                    for pod in pods
                    if (owner := _controller_owner(pod.metadata.owner_references if pod.metadata else None))
                    and owner.kind == "StatefulSet"
                    and owner.name == workload_name
                ]

            running_pods = [
                pod
                for pod in pods
                if pod.metadata and pod.metadata.name and pod.status and pod.status.phase == "Running"
            ]
            if not running_pods:
                raise K8sIntegrationError("该工作负载当前没有 Running Pod")

            running_pods.sort(key=lambda pod: (not _all_containers_ready(pod), pod.metadata.name))
            pod = running_pods[0]
            containers = []
            for container in pod.spec.containers or []:
                keys: list[str] = []
                error: str | None = None
                try:
                    response = stream(
                        core_api.connect_get_namespaced_pod_exec,
                        pod.metadata.name,
                        namespace,
                        container=container.name,
                        command=[
                            "/bin/sh",
                            "-c",
                            "xargs -0 -n 1 /bin/sh -c "
                            "'entry=$1; printf \"%s\\n\" \"${entry%%=*}\"' "
                            "_ < /proc/self/environ",
                        ],
                        stderr=True,
                        stdin=False,
                        stdout=True,
                        tty=False,
                        _preload_content=False,
                        _request_timeout=settings.k8s_read_timeout_seconds,
                    )
                    response.run_forever(timeout=settings.k8s_read_timeout_seconds)
                    if response.is_open():
                        response.close()
                        raise TimeoutError("Pod Exec timed out")
                    if response.returncode != 0:
                        raise K8sIntegrationError("Pod Exec command failed")
                    output = response.read_stdout()
                    keys = sorted(
                        {
                            line.strip()
                            for line in str(output).splitlines()
                            if line.strip() and line.strip().isidentifier()
                        }
                    )
                except (
                    ApiException,
                    AttributeError,
                    K8sIntegrationError,
                    TimeoutError,
                    WebSocketException,
                    OSError,
                    ValueError,
                ):
                    error = "容器不包含 /bin/sh 或 xargs，或当前 K8S 凭证没有 pods/exec 权限"
                containers.append(
                    {
                        "container_name": container.name,
                        "keys": keys,
                        "error": error,
                    }
                )
    except K8sIntegrationError:
        raise
    except _K8S_ERRORS as exc:
        raise K8sIntegrationError(_safe_error(exc)) from exc

    return {
        "namespace": namespace,
        "workload": {
            "kind": "Deployment" if normalized_kind == "deployment" else "StatefulSet",
            "name": workload_name,
        },
        "pod_name": pod.metadata.name,
        "containers": containers,
    }


_K8S_ERRORS = (
    ApiException,
    ConfigException,
    CredentialConfigurationError,
    InvalidTag,
    OSError,
    Urllib3HTTPError,
    ValueError,
    yaml.YAMLError,
)


def _label_selector(selector) -> str:
    parts = [f"{key}={value}" for key, value in sorted((selector.match_labels or {}).items())]
    for expression in selector.match_expressions or []:
        values = ",".join(sorted(expression.values or []))
        if expression.operator in {"In", "NotIn"}:
            parts.append(f"{expression.key} {expression.operator.lower()} ({values})")
        elif expression.operator == "Exists":
            parts.append(expression.key)
        elif expression.operator == "DoesNotExist":
            parts.append(f"!{expression.key}")
    if not parts:
        raise K8sIntegrationError("工作负载没有可用的 Pod selector")
    return ",".join(parts)


def _all_containers_ready(pod) -> bool:
    statuses = pod.status.container_statuses or []
    return bool(statuses) and all(status.ready for status in statuses)


def _api_client(cluster: dict) -> client.ApiClient:
    configuration = client.Configuration()
    if not cluster.get("credential_ciphertext") or not cluster.get("credential_nonce"):
        raise CredentialConfigurationError("集群尚未保存 K8S 凭证")
    content = decrypt_credential(
        bytes(cluster["credential_ciphertext"]),
        bytes(cluster["credential_nonce"]),
    )
    config.load_kube_config_from_dict(
        config_dict=yaml.safe_load(content),
        context=cluster.get("context_name") or None,
        client_configuration=configuration,
        persist_config=False,
    )
    if cluster.get("api_server_url"):
        configuration.host = cluster["api_server_url"].rstrip("/")
    # A false database flag may explicitly disable verification, while a true
    # flag must not overwrite insecure-skip-tls-verify from the kubeconfig.
    if not bool(cluster.get("verify_ssl", True)):
        configuration.verify_ssl = False
    return client.ApiClient(configuration)


def _request_timeout() -> tuple[int, int]:
    return (
        settings.k8s_connect_timeout_seconds,
        settings.k8s_read_timeout_seconds,
    )


def _controller_owner(owner_references) -> object | None:
    references = owner_references or []
    return next(
        (owner for owner in references if getattr(owner, "controller", False)),
        references[0] if references else None,
    )


def _safe_error(exc: Exception) -> str:
    message = str(exc).strip() or exc.__class__.__name__
    normalized_message = message.lower()
    if "certificate verify failed" in normalized_message and "ip address mismatch" in normalized_message:
        return (
            "TLS 证书校验失败：API Server 证书不包含当前 IP。"
            "请配置 tls-server-name，或仅在受信网络中设置 insecure-skip-tls-verify: true"
        )
    if "certificate verify failed" in normalized_message:
        return "TLS 证书校验失败：请检查 kubeconfig 中的 CA、server 地址和证书有效期"
    if "connection refused" in normalized_message:
        return "K8S API 连接被拒绝：请检查 6443 端口、安全组和 API Server 监听状态"
    return message[:1000]
