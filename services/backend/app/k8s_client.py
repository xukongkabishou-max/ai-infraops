from cryptography.exceptions import InvalidTag
from kubernetes import client, config
from kubernetes.client.exceptions import ApiException
from kubernetes.config.config_exception import ConfigException
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
    except (ApiException, ConfigException, CredentialConfigurationError, InvalidTag, OSError, ValueError, yaml.YAMLError) as exc:
        raise K8sIntegrationError(_safe_error(exc)) from exc

    return sorted(
        item.metadata.name
        for item in response.items
        if item.metadata and item.metadata.name
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
    except (ApiException, ConfigException, CredentialConfigurationError, InvalidTag, OSError, ValueError, yaml.YAMLError) as exc:
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
    configuration.verify_ssl = bool(cluster.get("verify_ssl", True))
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
    return message[:1000]
