# AI InfraOps

AI InfraOps 是一个面向统一运维的长期项目，目标是把集群、用户、权限、中间件、数据链路、告警和可观测性整合到一个平台里。

## 当前状态

- `apps/admin-web`：普通用户控制台，登录页已接入 FastAPI RBAC 校验；当前已搭好“机器信息管理、业务系统管理、中间件系统管理、监控系统集成”的静态页面骨架，并保留已添加主机的 node-exporter 指标展示。
- `apps/backend-admin-web`：后端 RBAC 管理页面，运行在 `3001` 端口；当前可管理 RBAC 基础数据和“机器资源信息”里的主机添加/删除。
- `apps/user-web`：预留给普通用户门户。
- `services/backend`：FastAPI + MySQL 后端，当前只覆盖登录、用户、角色、权限、菜单。
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
  init_mysql.py            读取根目录 .env，连接 MySQL，执行 services/backend/sql/init.sql。
```

## 机器资源信息

当前第一版通过 node-exporter 获取主机指标：

```text
GET    /api/hosts                 查看主机列表，并刷新活跃/无法连接状态
POST   /api/hosts                 添加或更新主机，字段包含 node_exporter_url、hostname、public_ip、private_ip
DELETE /api/hosts/{host_id}       删除主机
GET    /api/hosts/{host_id}/metrics 查看 CPU 使用率、内存使用率、/ 目录磁盘使用率及对应容量详情
```

node-exporter 可以稳定提供 CPU 累计时间、CPU 核数、内存、磁盘、系统内核和 `node_uname_info` 里的 nodename。CPU 使用率当前通过短间隔采样 `node_cpu_seconds_total`，按非 idle 时间占比计算；内存和磁盘使用率按已用/总量计算。公网 IP 当前从填写的 exporter URL 推断；私网 IP 不建议依赖 node-exporter 自动识别，后台添加主机时保留手动填写字段。

## 普通用户控制台功能骨架

当前 `apps/admin-web` 登录后左侧功能栏先搭静态页面，后续按模块逐步接入真实 API：

```text
机器信息管理       环境 API 地址、机器账号列表、中间件账号获取
业务系统管理       服务 NodePort、镜像 tag、GPU 模型显存、环境变量 key
中间件系统管理     Nacos key 获取、MySQL/Doris/Redis/Kafka 可用性快速校验
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
