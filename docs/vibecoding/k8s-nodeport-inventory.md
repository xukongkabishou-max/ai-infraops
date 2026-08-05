# K8S NodePort 公网调用地址

## 目标

普通用户在“业务系统管理 → 服务 NodePort”中选择数据库已登记的所属环境主机，再选择该主机 K8S 集群中的 Namespace，手动查询 NodePort 类型 Service。页面按 Service 的每个 NodePort 端口展示公网调用地址。

环境、主机、公网 IP 和 K8S 凭证继续复用以下数据关系：

```text
infra_environments
  -> machine_hosts.environment_id
  -> k8s_clusters.host_id
```

NodePort 是 K8S 实时状态，不写入事实表。FastAPI 使用已加密保存的 kubeconfig 请求 CoreV1 Services API，并只保留 `spec.type=NodePort` 且存在 `nodePort` 的端口。

## API 链路

```text
GET /api/k8s/nodeports/hosts
GET /api/k8s/nodeports/namespaces?host_id=...
GET /api/k8s/nodeports?host_id=...&namespace=...
```

三条接口都要求 `user_web` 会话和 `k8s:nodeport:list` 权限。接口不会返回 kubeconfig、密文或 nonce。

NodePort 查询按一个端口一条记录返回：

```json
{
  "service_name": "example-nodeport",
  "service_display_name": "example",
  "port_name": "http",
  "protocol": "TCP",
  "service_port": 8080,
  "node_port": 30080,
  "public_address": "203.0.113.10:30080",
  "visible": true,
  "note": null
}
```

`service_display_name` 只移除末尾的 `-nodeport`。Service 只有一个 NodePort 时，页面使用“服务名 + 服务公网调用地址”；同一个 Service 有多个 NodePort 时，再追加 `port_name` 区分。缺少 `port_name` 时后端使用 `servicePort-protocol` 生成稳定名称。

## 可见性与审计预留

当前策略为 `allow_all`：普通用户可以枚举所有已接入 K8S 集群的 Namespace，并查看其中全部 NodePort。API 响应保留 `policy.mode`、`visible` 和 `note` 字段，后台管理页保留 NodePort 展示策略区域。

后续实现规则时，应由后端按环境、Namespace、Service 和端口名过滤后再返回：

- 普通用户不可见的端口不应发送到浏览器。
- 常用端口注释由后端合并到 `note`。
- 查询日志记录用户、主机、Namespace 和返回数量，不记录 kubeconfig。
- 管理规则建议单独建表，不修改 K8S 实时结果结构。

## K8S 权限

查询凭证至少需要：

```text
namespaces: get, list
services: get, list
```
