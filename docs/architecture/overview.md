# 架构总览

AI InfraOps 采用 monorepo 结构，前端、后端服务、共享包、基础设施配置和项目文档统一放在一个仓库中。

## 前端

- `apps/admin-web`：普通用户控制台，用于展示机器信息、业务系统、中间件系统和监控系统集成等运维视图。
- `apps/backend-admin-web`：后台管理控制台，维护 RBAC、环境主机、K8S 凭证以及 Nacos、Doris 连接信息，并预留更多账号资产和权限范围入口。
- `apps/user-web`：普通用户门户，用于自助查看资源、申请权限、执行被授权的运维动作。

### 普通用户控制台功能骨架

`apps/admin-web` 当前先按静态页面搭好以下侧边功能栏，后续再逐步接入真实 API：

- `机器信息管理`：下分 `环境 API 地址`、`机器账号列表`、`中间件账号获取` 三个子页面。环境 API 地址只给研发展示 CPU、内存、根目录磁盘、公网 IP、私网 IP、Loki 日志、K8S Pod 状态与事件的查询地址，不在该子页直接执行查询。
- `业务系统管理`：下分 `服务 NodePort`、`镜像 tag`、`GPU 模型显存`、`环境变量 key` 四个子页面。NodePort 页通过“已配置凭证的环境主机 → namespace”筛选，实时读取 NodePort Service 并拼接主机公网 IP；镜像页查询真实 Running Pod 镜像；环境变量页只开放后台白名单中的 Namespace，并按 Deployment/StatefulSet 查询一个 Running Pod 的容器 Key。
- `中间件系统管理`：下分 `Nacos 配置目录`、`数据库可用性校验` 两个子页面。Nacos 配置目录已按 Namespace、Group、DataId 和格式实时查询，并且不读取配置正文；后续选择具体 DataId 时再由后端结构化解析器移除 value 后返回 Key 树。数据库校验后续由后端脚本执行。
- `监控系统集成`：预留 Prometheus、Loki、告警中心和 SLO 守护等集成入口。

静态页面中的示例地址只使用占位值，不记录真实环境 IP、端口、账号或密码。

## 后端

后端不强行绑定一种语言，按领域拆成多个服务：

- `services/api-gateway`：统一入口，负责路由、聚合、鉴权上下文透传和前端 BFF 能力。
- `services/auth-service`：用户、角色、权限、组织、登录认证和审计。
- `services/python-ops-api`：Python 生态能力，例如自动化脚本、AI 辅助分析、数据处理、FastAPI 接口。
- `services/k8s-service`：Kubernetes API 集成，负责集群、命名空间、工作负载、事件和资源指标。
- `services/middleware-service`：中间件资源发现、用户盘点、权限创建和变更。

## 文档与素材

- `docs/vibecoding`：记录每次 vibecoding 做了什么、参考了哪些项目和知识点。
- `docs/references`：沉淀外部开源项目、文章、设计参考和 API 文档。
- `md-assets`：只存放 Markdown 文档引用的图片，不放业务代码。

## 演进原则

- 先做清晰边界，再逐步补服务实现。
- 前端先有可用体验，后端按真实集成逐个落地。
- 权限、审计和中间件用户管理是平台核心能力，应尽早抽象成稳定模型。
- K8S、Doris、Milvus、数据库和消息队列等集成可以按 adapter 方式逐步加入。

## 环境与 K8S 资源边界

- `infra_environments` 是环境主数据，环境名称由用户维护，内部编码由后端生成。
- `machine_hosts.environment_id` 表示主机所属环境。
- `machine_hosts.namespace_keys` 保存该主机允许普通用户查询 Pod 环境变量 Key 的 Namespace JSON 白名单；空数组表示不开放。
- `k8s_clusters.host_id` 唯一绑定已添加主机，`environment_id` 同步记录其环境归属。
- kubeconfig 不以明文入库、不入 Git。后端使用 AES-256-GCM 加密后，将密文、随机 nonce、指纹和原文件名保存到 `k8s_clusters`；主密钥只从 `.env` 读取。
- 当前管理端采用一个完整主机表单：可粘贴 kubeconfig 文本，并通过列表“编辑”更新已有属性；编辑时凭证留空即保留原值。
- namespace 和 Running Pod 镜像列表来自 K8S API 实时查询，只按 Deployment、StatefulSet、DaemonSet 聚合 Pod 名称、副本数和容器完整镜像，不创建镜像事实表。
- K8S 节点资源查询通过 kubeconfig 实时列出 Node，并自动发现 Prometheus Service；后端经 K8S Service Proxy 只读查询 node-exporter 指标。有凭证时返回整个集群，无凭证时回退到单机 node-exporter，指标结果不写入事实表。
- NodePort 列表同样来自 K8S API 实时查询，每个 Service 端口独立返回，公网地址由 `machine_hosts.public_ip` 与 `nodePort` 拼接；当前普通用户默认可见全部 Namespace，后续由后端展示策略过滤并合并注释。
- 环境变量查询只支持 Deployment、StatefulSet。后端验证 Namespace 白名单后选择一个 Running Pod，并在容器内移除 value，只返回容器名和 Key；该链路要求 `pods/exec` 权限，因此应使用独立、最小权限的 K8S ServiceAccount。

## 中间件凭证边界

- `middleware_instances.environment_id` 复用环境主数据，当前接入类型为 Nacos、Doris 和 MySQL；MySQL 实例额外保存 Grafana 仪表盘地址，旧 mysql-exporter 字段仅保留历史兼容。
- 中间件密码使用 AES-256-GCM 加密后保存，管理列表接口只选择环境、类型、名称、URL、用户名和状态等公开字段。
- 密码明文只存在于管理端提交和后端请求处理期间，不写日志、不回显、不进入 Git。
- 中间件实例接口要求后台管理会话，并按列表、新增、修改、删除操作检查 `middleware:*` 权限。修改时密码留空表示保留已有密文。
- `configured` 表示已登记，不等于连通；配置目录查询由 Nacos adapter 更新 `active` 或 `unreachable`。
- 普通用户端只能通过 `user_web` 会话和 `nacos:catalog:list` 权限访问 Nacos 目录接口。环境列表不返回 URL 和用户名，目录响应使用字段白名单，仅保留 Namespace、Group、DataId 和格式。
- Doris 用户端接口使用 `doris:accounts:list` 权限，通过 FE MySQL 协议执行 `SHOW ALL GRANTS`；只返回账号标识、Host、备注等安全字段，不返回登记连接、密码、密码哈希或 Doris 的 `Password` 列。
- MySQL 用户端接口使用 `mysql:accounts:list` 权限，只查询 `mysql.user` 中的账号标识、Host、认证插件和状态字段，不查询或返回认证哈希。Doris/MySQL 的当前密码托管、显示、校验和同步仅限超级管理员，并分别使用独立密文域和审计表。
- MySQL 仪表盘使用独立的 `mysql:dashboard:view` 权限。RD 可以读取环境、实例名称和仪表盘 URL，但该接口不返回 MySQL 连接地址、管理用户名或凭证；iframe 是否可用仍受 Grafana 的嵌入策略和登录权限控制。

## 日志与诊断边界

- FastAPI 统一输出 JSON 结构化应用日志，日志包含 `X-Request-ID`、接口路径、状态码和耗时。
- 日志默认写入 `.local/logs/backend.log` 并按大小滚动，`.local` 不进入 Git。
- 请求体、登录密码、数据库密码和 kubeconfig 不写入日志。
- node-exporter 的最近探测状态和可读错误继续保存在 `machine_hosts.status`、`machine_hosts.last_error`，用于管理页面即时展示；日志负责提供更完整的请求和异常上下文。
