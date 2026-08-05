# K8S Pod 环境变量 Key 查询

## 目标

普通用户可以查看被授权 Namespace 中 Deployment 或 StatefulSet 的运行时环境变量名称，但不能获取任何 value。管理端直接在主机记录中维护 Namespace 白名单，不新增第二套环境或集群模型。

## 数据模型

`machine_hosts.namespace_keys` 使用 MySQL JSON 保存 Namespace 名称数组，例如：

```json
["dev", "prod"]
```

空数组表示该主机不开放环境变量 Key 查询。字段由 `008_k8s_env_keys.sql` 添加；该迁移同时创建 `k8s:env:list` 权限并授予 `super_admin`。

## API 链路

```text
所属环境 / 主机
  -> 与真实集群 Namespace 取白名单交集
  -> 查询 Deployment、StatefulSet
  -> 根据 selector 和 ownerReferences 找到所属 Running Pod
  -> 优先选择容器全部 Ready 的一个副本
  -> 对每个普通容器执行 Key-only 命令
  -> 返回 Pod、容器名和 Key 数组
```

接口：

```text
GET /api/k8s/env/hosts
GET /api/k8s/env/namespaces
GET /api/k8s/env/workloads
GET /api/k8s/env/keys
```

每个接口都要求 `user_web` Bearer 会话和 `k8s:env:list`。后端在 Namespace、工作负载和最终 Key 查询时重复校验白名单，不能通过伪造 URL 参数访问未开放 Namespace。

## Value 隔离

不执行原始 `env` 后再把 value 交给 FastAPI 过滤。平台通过 Pod Exec 在容器内按环境变量原生的 NUL 分隔记录读取当前进程环境，并且每条记录只打印第一个 `=` 前的名称：

```text
xargs -0 -n 1 /bin/sh -c 'entry=$1; printf "%s\n" "${entry%%=*}"' _ < /proc/self/environ
```

值即使包含换行也只会作为单条 NUL 分隔记录处理，不会成为输出。因此 WebSocket 返回内容只包含变量名，API 响应、应用日志和浏览器都不会接收 value。输出只接受合法变量名称并排序去重。

## K8S 权限

专用 ServiceAccount 至少需要：

```text
deployments、statefulsets：get、list
replicasets：get、list
pods：get、list
pods/exec：create
```

`pods/exec` 比普通只读权限更高。生产环境应按允许的 Namespace 创建 Role/RoleBinding，不应复用 cluster-admin。数据库白名单是平台侧授权边界，K8S RBAC 是集群侧第二道边界。

## 兼容限制

- 第一版只查询普通容器，不查询 initContainer 和 ephemeralContainer。
- distroless 等镜像可能没有 `/bin/sh`、`xargs` 或不可读取 procfs，此时返回容器级错误，其他容器仍正常展示。
- 只选择一个 Running Pod 副本。若各副本运行时注入内容不同，页面结果只代表本次选中的 Pod，响应中会明确返回 Pod 名称。
- 平台不缓存 Key 清单，每次点击按钮实时查询集群。

## 前端分页

每个容器独立展示 Key 列表，固定每页 15 条。分页控件位于列表右下角，提供首页、上一页、连续页码、下一页和末页操作，同时显示当前范围、总条数及总页数。重新查询或切换工作负载后，新结果从第一页开始，多个容器之间的页码互不影响。

每个容器支持独立搜索。默认对输入内容执行不区分大小写的完整 Key 匹配；开启“区分大小写”后按原始字符匹配，开启“前缀模糊搜索”后改为前缀匹配。搜索结果继续按每页 15 条分页，修改搜索词或匹配选项时自动回到第一页；没有匹配项时在列表区域显示明确的空结果提示。
