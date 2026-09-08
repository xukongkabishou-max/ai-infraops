import base64
from unittest import TestCase

import yaml

from app.credential_crypto import normalize_kubeconfig_tls, validate_kubeconfig
from app.schemas import HostCreateRequest


def kubeconfig(cluster_overrides: dict | None = None, user_overrides: dict | None = None) -> str:
    cluster = {"server": "https://k8s.example.internal:6443"}
    cluster.update(cluster_overrides or {})
    user = {"token": "test-token"}
    user.update(user_overrides or {})
    return yaml.safe_dump(
        {
            "apiVersion": "v1",
            "kind": "Config",
            "clusters": [{"name": "cluster", "cluster": cluster}],
            "contexts": [
                {
                    "name": "admin@cluster",
                    "context": {"cluster": "cluster", "user": "admin"},
                }
            ],
            "current-context": "admin@cluster",
            "users": [{"name": "admin", "user": user}],
        },
        sort_keys=False,
    )


class KubeconfigTlsTests(TestCase):
    def test_host_request_skips_tls_verification_by_default(self) -> None:
        payload = HostCreateRequest(
            node_exporter_url="http://host.example:9100/metrics",
            hostname="host-01",
            environment_name="测试环境",
        )

        self.assertTrue(payload.k8s_skip_tls_verify)

    def test_adds_skip_tls_verification_to_every_cluster(self) -> None:
        content = yaml.safe_load(kubeconfig())
        content["clusters"].append(
            {
                "name": "cluster-2",
                "cluster": {"server": "https://k8s-2.example.internal:6443"},
            }
        )

        normalized = normalize_kubeconfig_tls(
            yaml.safe_dump(content, sort_keys=False),
            skip_tls_verify=True,
        )
        clusters = yaml.safe_load(normalized)["clusters"]

        self.assertTrue(all(item["cluster"]["insecure-skip-tls-verify"] for item in clusters))

    def test_removes_skip_tls_verification_when_disabled(self) -> None:
        normalized = normalize_kubeconfig_tls(
            kubeconfig({"insecure-skip-tls-verify": True}),
            skip_tls_verify=False,
        )
        cluster = yaml.safe_load(normalized)["clusters"][0]["cluster"]

        self.assertNotIn("insecure-skip-tls-verify", cluster)

    def test_rejects_invalid_inline_client_certificate(self) -> None:
        invalid_certificate = base64.b64encode(
            b"-----BEGIN CERTIFICATE-----\ninvalid\n-----END CERTIFICATE-----\n"
        ).decode("ascii")

        with self.assertRaisesRegex(ValueError, "客户端证书不是有效 PEM"):
            validate_kubeconfig(
                kubeconfig(
                    user_overrides={
                        "token": "",
                        "client-certificate-data": invalid_certificate,
                    }
                )
            )
