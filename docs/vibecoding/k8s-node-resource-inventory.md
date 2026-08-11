# K8S 节点资源查询

## 目标

后台主机记录已保存 kubeconfig 时，普通用户控制台按该凭证查询整个 K8S 集群的节点资源；没有 kubeconfig 时继续查询该记录的 node-exporter。单节点 K8S 与多节点 K8S 使用同一接口，区别只是返回节点数量。

页面展示以下只读信息：

- K8S Node 名称、Ready 状态和节点 IP
- 最近 5 分钟 CPU 平均使用率与逻辑核数
- 内存使用率、总量、已用量和可用量
- `/` 根目录使用率、总量、已用量和剩余量

## 查询链路

```text
用户页面加载全部已登记主机
  -> FastAPI 读取并解密该主机绑定的 kubeconfig
  -> K8S API list Node 与 list Service
  -> 自动选择 Prometheus HTTP Service
  -> K8S Service Proxy 调用 Prometheus instant query
  -> 通过 node_uname_info 的 instance/nodename 合并节点指标
  -> Prometheus 缺少节点指标时，通过 API Server 只读查询 kubelet stats/summary
  -> 单节点的 kubelet 查询也不可用时，最后回退到登记的 node-exporter URL
  -> 返回结构化节点列表
```

## 页面交互

- 后台主机编辑会回填主机名、所属环境、node-exporter URL、主机用户管理地址、公网/私网 IP 和 Namespace Key 白名单。
- Kubeconfig 正文包含客户端私钥，不从后端解密回传浏览器；编辑时显示原凭证文件名和已加密保存状态，正文留空会保留原凭证。
- 页面不再按资源入口筛选，所有已登记主机和 K8S 节点统一显示在一张表格中。
- 表格支持按所属环境即时筛选；选择某个环境时保留该环境下的全部 K8S 节点或独立主机。
- 同一 K8S 集群的节点共用一个“所属环境”分组，节点名称、CPU、内存和根目录指标分别占一行。
- “全部刷新指标”并发刷新所有环境；每个环境的“刷新指标”只刷新该环境，刷新期间继续保留上一次成功数据。
- 单个环境查询失败不会清空或阻塞其他环境，错误信息只显示在对应环境分组中。

后端自动排除 exporter、operator、alertmanager、pushgateway 等非 Prometheus Server Service，优先选择带 Prometheus 标签、HTTP 端口为 `9090` 或端口名为 `http-web` 的 Service。Prometheus 没有采集 node-exporter 时不会直接返回零值，而是继续读取 kubelet Summary API；只有所有只读指标源都不可用时才显示暂无指标。

## API

```text
GET /api/resources/hosts
GET /api/resources/hosts/{host_id}/metrics
```

两个接口都要求 `user_web` 会话和 `host:list` 权限。列表接口不返回 kubeconfig、密文、nonce 或 Prometheus 内部地址。指标接口只执行 K8S `list` 和 HTTP `GET` 代理请求，不创建、更新、删除任何 K8S 资源。

## 三种情况

- 无 K8S：调用已登记的 node-exporter，只返回一台独立主机。
- 单节点 K8S：K8S Node 列表只有一项，返回一个节点指标对象。
- 多节点 K8S：按 K8S Node 名称返回全部节点；Prometheus 缺少某节点时逐节点回退到 kubelet Summary API，仍失败时保留节点并标记“暂无指标”。

## Linux 只读验证

安装 `kubectl`、`jq` 后，可以用下面的命令复现内存使用率查询。变量使用集群中的实际 Namespace、Service 名和 Service 端口名填写。

```bash
KUBECONFIG_FILE="/root/.kube/config"
PROM_NAMESPACE="monitoring"
PROM_SERVICE="prometheus-server"
PROM_PORT_NAME="http-web"
PROMQL_ENCODED='100%20%2A%20%281%20-%20node_memory_MemAvailable_bytes%20%2F%20node_memory_MemTotal_bytes%29%20%2A%20on%28instance%29%20group_left%28nodename%29%20node_uname_info'

kubectl \
  --kubeconfig="$KUBECONFIG_FILE" \
  --insecure-skip-tls-verify=true \
  get --raw "/api/v1/namespaces/${PROM_NAMESPACE}/services/http:${PROM_SERVICE}:${PROM_PORT_NAME}/proxy/api/v1/query?query=${PROMQL_ENCODED}" |
jq -r '.data.result[] | [.metric.nodename, .metric.instance, (((.value[1] | tonumber) * 100 | round) / 100 | tostring) + "%"] | @tsv' |
column -t
```

该命令和平台接口都只读取数据。生产环境应优先正确配置 CA 和 `tls-server-name`；`insecure-skip-tls-verify` 只用于受信网络中的临时验证。
