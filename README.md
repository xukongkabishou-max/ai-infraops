# AI InfraOps

AI InfraOps 是一个面向统一运维的长期项目，目标是把集群、用户、权限、中间件、数据链路、告警和可观测性整合到一个平台里。

## 当前状态

- `apps/admin-web`：普通用户控制台，登录页和动态菜单已接入 FastAPI RBAC；研发只显示业务系统和中间件系统，运维可查看全部功能。
- `apps/backend-admin-web`：后端 RBAC 管理页面，运行在 `3001` 端口；维护环境主机、K8S 凭证和中间件连接信息，并提供安全审计日志。
- `apps/user-web`：预留给普通用户门户。
- `services/backend`：FastAPI + MySQL 后端，当前覆盖 RBAC、机器资源、环境主机、K8S 凭证、Running Pod 镜像与环境变量 Key 查询、Nacos 配置目录以及 Doris/MySQL 账号查询。
- `services/linux-agent`：部署到 Linux 主机的只读 Go Agent，提供本地账号清单与数量，不读取密码哈希。
- `services`：后续可以按语言和领域继续拆分服务。
- `docs`：记录架构、vibecoding 过程、参考项目和知识点。
- `md-assets`：只放 Markdown 文档引用的截图、设计图和静态图片。
- `infra`：预留 Docker、K8S、Helm、Compose 等部署和基础设施配置。
- `packages`：预留前后端共享类型、公共 UI、统一配置等可复用包。
- `scripts`：项目级开发、代码生成、迁移、运维脚本入口；具体服务自己的脚本放在各自服务目录下，例如 `services/backend/scripts/init_mysql.py`。

## 本地运行

启动后台管理前端：

```powershell
npm run dev:admin
```

启动后端 RBAC 管理页面：

```powershell
npm run dev:backend-admin
```

初始化 MySQL：

```powershell
cd services/backend
micromamba run -n base python scripts/init_mysql.py
```

启动 FastAPI 后端：

```powershell
cd services/backend
micromamba run -n base python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

等价于：

```powershell
cd apps/admin-web
npm run dev
```

访问：

```text
http://localhost:3000
http://localhost:3001
http://127.0.0.1:8000/health
```

## 根命令说明

这些命令定义在最外层 `package.json`，统一从项目根目录执行：

```text
npm run dev:admin          启动普通用户控制台，端口 3000
npm run build:admin        构建普通用户控制台
npm run lint:admin         检查普通用户控制台代码

npm run dev:backend-admin  启动后端 RBAC 管理页面，端口 3001
npm run build:backend-admin 构建后端 RBAC 管理页面
npm run lint:backend-admin 检查后端 RBAC 管理页面代码

npm run dev:rbac-api       启动 FastAPI RBAC 后端，端口 8000
npm run init:mysql         执行 MySQL 初始化 SQL，创建 RBAC 库表和初始 admin 账号
```

## 脚本目录说明

```text
scripts/
  README.md                项目级脚本目录说明。后续放跨应用、跨服务的通用脚本。

services/backend/scripts/
  init_mysql.py            读取根目录 .env，连接 MySQL，执行 init.sql 及编号迁移 SQL。
  check_nacos_catalog.py   使用首个已登记 Nacos 做目录冒烟检查，只输出实例、Namespace、配置和格式数量。
```

## 机器资源信息

当前第一版通过 node-exporter 获取主机指标：

```text
GET    /api/hosts                 查看主机列表和最近一次探测状态
POST   /api/hosts                 添加主机，同时记录环境和可选 kubeconfig 文本
PUT    /api/hosts/{host_id}       更新已有主机；凭证留空时保留原值
POST   /api/hosts/{host_id}/probe 重新检测 node-exporter 并更新连接原因
DELETE /api/hosts/{host_id}       删除主机
GET    /api/hosts/{host_id}/metrics 查看 CPU 使用率、内存使用率、/ 目录磁盘使用率及对应容量详情
GET    /api/resources/hosts         用户端查看可查询的集群或独立主机入口
GET    /api/resources/hosts/{host_id}/metrics 用户端查询整个 K8S 集群或独立主机资源
GET    /api/linux-accounts/hosts              用户端查看已配置账号 Agent 的主机
GET    /api/linux-accounts/hosts/{host_id}    实时查询指定主机的本地账号清单
```

node-exporter 可以稳定提供 CPU 累计时间、CPU 核数、内存、磁盘、系统内核和 `node_uname_info` 里的 nodename。CPU 使用率当前通过短间隔采样 `node_cpu_seconds_total`，按非 idle 时间占比计算；内存和磁盘使用率按已用/总量计算。公网 IP 当前从填写的 exporter URL 推断；私网 IP 不建议依赖 node-exporter 自动识别，后台添加主机时保留手动填写字段。

用户端“集群与主机资源”会判断主机是否绑定 K8S 凭证：有凭证时通过 K8S Service Proxy 自动发现 Prometheus，实时查询整个集群所有 Node 的最近 5 分钟 CPU 使用率、内存和根目录容量；无凭证时回退到该主机的 node-exporter。单节点 K8S 返回一项，多节点返回全部节点，缺少指标的节点仍会展示并标明原因。详细设计见 `docs/vibecoding/k8s-node-resource-inventory.md`。

FastAPI 会将请求耗时、请求 ID、主机探测和异常写入 `.local/logs/backend.log`，并按文件大小自动滚动。后台管理页面直接展示 `last_error` 中的连接失败原因，并提供“重新检测”操作；日志不会记录请求体、密码和 kubeconfig。

后台主机表单可以选填“主机用户管理地址”。普通用户端按环境和主机查询时，FastAPI 使用仅保存在 `.env` 的 Bearer Token 调用 Go Agent；浏览器不会获得 Agent 地址或 Token。当前只读取 `/etc/passwd`，详细边界见 `docs/vibecoding/linux-account-agent.md`。

## K8S 镜像查询

数据关系为“环境 → 主机 → K8S 凭证”，凭证记录通过唯一 `host_id` 绑定主机，镜像不缓存到 MySQL。用户端只加载已配置凭证的环境主机，选择 namespace 并点击按钮后，FastAPI 实时读取 Running Pod，并按 Deployment、StatefulSet、DaemonSet 返回 Pod 名称、副本数和每个容器的完整镜像。

```text
GET    /api/k8s/hosts                         查看已配置 K8S 凭证的环境主机
GET    /api/k8s/namespaces?host_id=...        实时读取 namespace
GET    /api/k8s/images?host_id=...&namespace=... 实时读取 Running Pod 镜像
```

3001 页面不提供独立集群表单，只在统一主机表单中提供“K8S 凭证内容”输入栏。后端使用 AES-256-GCM 加密 kubeconfig 后把密文、随机 nonce 和指纹存入 MySQL，并绑定对应主机；主密钥只存在根目录 `.env`。详细设计与操作见 `docs/vibecoding/k8s-image-inventory.md`。

## K8S 环境变量 Key 查询

后台主机表单通过 `Namespace Key 白名单` 配置允许普通用户查询的 Namespace。用户端按“所属环境 → Namespace → Deployment/StatefulSet”选择工作负载，后端从其 Running Pod 中选择一个副本，并分别返回每个普通容器的环境变量名称。

```text
GET /api/k8s/env/hosts
GET /api/k8s/env/namespaces?host_id=...
GET /api/k8s/env/workloads?host_id=...&namespace=...
GET /api/k8s/env/keys?host_id=...&namespace=...&kind=...&workload=...
```

以上接口要求 `user_web` Bearer 会话和 `k8s:env:list` 权限。Namespace 白名单在每层 API 服务端重新校验，容器内命令只输出 Key，FastAPI 不接收 value。完整设计见 `docs/vibecoding/k8s-env-key-inventory.md`。

KubeKey kubeconfig 将 API Server 域名替换为外部可达 IP 后，如果证书不包含该 IP，应在同一个 cluster 配置中保留 `certificate-authority-data` 并设置 `tls-server-name` 为证书内的原域名。仅在受信网络临时排障时使用 `insecure-skip-tls-verify: true`；平台会遵循这两个 kubeconfig 字段。

## Nacos 连接信息

后台管理页面的“中间件资源信息 → 中间件实例”提供所属环境、Nacos URL、用户名和密码四个字段。环境复用 `infra_environments`，连接记录保存到 `middleware_instances`；密码使用 AES-256-GCM 加密，列表接口不会查询或返回密码密文。

```text
GET    /api/middleware/instances              查看已登记的中间件实例
POST   /api/middleware/instances              添加 Nacos、Doris 或 MySQL 连接信息
DELETE /api/middleware/instances/{instance_id} 删除连接信息
GET    /api/nacos/instances                   用户端获取已登记的 Nacos 环境
GET    /api/nacos/instances/{instance_id}/catalog 实时读取 Namespace、Group、DataId 和格式
```

目录接口使用 `user_web` Bearer 会话和 `nacos:catalog:list` 权限。FastAPI 只映射 Nacos 元数据接口中的 Namespace、Group、DataId 和格式，显式丢弃 `content`、MD5 等其他字段；不会把 URL、用户名、密码或配置正文返回浏览器。详细边界见 `docs/vibecoding/nacos-connection-management.md`。

## Doris 账号信息

后台在同一个中间件实例表单中切换到 Doris，登记所属环境、实例名称、FE Host、查询端口、管理用户名和密码。密码沿用中间件 AES-256-GCM 加密机制，用户端只获取环境和实例选项。

```text
GET /api/doris/instances
GET /api/doris/instances/{instance_id}/accounts
```

账号接口通过 Doris FE 的 MySQL 协议执行 `SHOW ALL GRANTS`，要求登记账号具有查看全部用户授权的 `GRANT_PRIV`。响应只保留用户标识、Host、备注、角色和授权范围，明确丢弃 `Password` 列；Doris 密码不可逆，也不会返回密码或密码哈希。完整边界见 `docs/vibecoding/doris-account-inventory.md`。

## MySQL 实例与账号

后台中间件实例表单支持登记所属环境、实例名称、MySQL Host、连接端口、管理用户名、管理密码和 `mysql-exporter URL`。管理密码使用现有 AES-256-GCM 机制加密保存，Exporter 地址作为后续指标展示的非敏感元数据单独保存。

普通用户端的“中间件账号获取”可以切换 Doris/MySQL，按所属环境和实例实时查询 MySQL 用户标识、Host、认证插件和账号状态。超级管理员还可加密登记当前密码、显示/复制、通过目标账号登录校验，并通过登记管理账号执行 `ALTER USER` 同步密码。账号列表不会读取或返回 MySQL 密码哈希；详细边界见 `docs/vibecoding/mysql-instance-management.md`。

## 普通用户控制台功能骨架

当前 `apps/admin-web` 登录后左侧功能栏先搭静态页面，后续按模块逐步接入真实 API：

```text
机器信息管理       环境 API 地址、机器账号列表、中间件账号获取
业务系统管理       服务 NodePort、镜像 tag、GPU 模型显存、环境变量 key
中间件系统管理     Nacos 配置目录、MySQL/Doris/Redis/Kafka 可用性快速校验
监控系统集成       Prometheus、Loki、告警中心、SLO 守护等入口预留
```

静态页面示例数据只使用占位 IP、占位 API 路径和脱敏密码，不记录真实环境 IP、端口、账号或密码。详细编码记录见 `docs/vibecoding/user-console-static-modules.md`。

## 登录会话

当前登录会话由 FastAPI 写入 Redis。3000 普通用户控制台和 3001 后端管理页面使用不同 `client_type`，因此两边登录态互不覆盖：

```text
user_web            3000 普通用户控制台
backend_admin_web   3001 后端管理页面
```

相关环境变量放在仓库根目录 `.env`，该文件已被 `.gitignore` 忽略：

```text
REDIS_HOST
REDIS_PORT
REDIS_PASSWORD
REDIS_DB
REDIS_TLS
SESSION_TTL_SECONDS
```

## 目录约定

```text
apps/
  admin-web/        普通用户控制台
  backend-admin-web/ 后端 RBAC 管理页面
  user-web/         普通用户使用的门户

services/
  backend/          FastAPI + MySQL 后端，第一阶段只做 RBAC
  api-gateway/      统一 API 网关
  auth-service/     认证、用户、角色、权限
  python-ops-api/   Python 自动化、数据处理、AI/脚本 API
  k8s-service/      Kubernetes API 集成
  middleware-service/ 中间件用户、权限和资源发现

packages/
  shared-types/     前后端共享类型和 DTO
  ui/               前端共用 UI 组件
  eslint-config/    统一 lint 配置
  tsconfig/         统一 TypeScript 配置

docs/
  architecture/     架构设计
  references/       外部开源项目、文章、知识点
  vibecoding/       vibecoding 过程记录

md-assets/          Markdown 引用图片
infra/              Docker、K8S、Helm、Compose
scripts/            开发、代码生成、运维脚本
```

## 前辈经验

本节用于记录 vibecoding 过程中参考过的公开项目、设计作品、框架文档和知识点。记录原则：

- 只记录公开来源、通用技术思路和可复用设计方法。
- 不记录任何真实环境 IP、端口、账号、密码、内网域名或生产拓扑。
- 如果后续参考了开源项目代码，需要补充许可证、仓库地址和具体借鉴范围。
- 如果只是 UI 风格、交互方式或架构思想参考，也要明确写成“灵感参考”，避免误认为直接复制代码。

当前参考记录：

| 类型 | 来源 | 借鉴范围 | 备注 |
| --- | --- | --- | --- |
| UI 灵感 | Dribbble: Jet login screen | 登录页的深色视觉、左侧登录表单与右侧科技感插画氛围 | 仅作视觉方向参考，未复制源文件 |
| 前端框架 | Next.js 官方文档 | `apps/admin-web`、`apps/backend-admin-web` 的应用结构、开发/构建方式 | 用于本地 demo 和后续前端工作区 |
| 前端样式 | Tailwind CSS 官方文档 | 页面布局、响应式栅格、深色控制台样式 | 当前主要用于快速搭建界面 |
| 后端框架 | FastAPI 官方文档 | 登录、RBAC、机器资源信息等 API 的组织方式 | 第一阶段 Python 后端选型 |
| 数据库 | MySQL 官方能力与常见 RBAC 设计 | 用户、角色、权限、菜单、主机信息等关系表建模 | 当前只做基础关系模型 |
| 会话管理 | Redis 常见 session 设计 | 按 `client_type` 隔离 3000 用户端与 3001 管理端会话 | 当前保存 opaque token 会话 |
| 运维指标 | Prometheus node-exporter 指标模型 | CPU、内存、磁盘、主机名、连通状态等指标采集思路 | 当前通过 node-exporter URL 采集 |
| Kubernetes API | [Pod Exec API](https://kubernetes.io/docs/reference/kubernetes-api/core/pod-v1/#connect-exec) | 通过 Pod `exec` 子资源在指定容器中执行 Key-only 命令 | 仅允许后台白名单 Namespace |
| Python 客户端 | [kubernetes-client/python](https://github.com/kubernetes-client/python) | 使用官方 `stream` 模块调用 Pod Exec WebSocket | 不记录 stdout，不返回 value |
