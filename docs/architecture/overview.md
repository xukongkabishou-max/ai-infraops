# 架构总览

AI InfraOps 采用 monorepo 结构，前端、后端服务、共享包、基础设施配置和项目文档统一放在一个仓库中。

## 前端

- `apps/admin-web`：普通用户控制台，用于展示机器信息、业务系统、中间件系统和监控系统集成等运维视图。
- `apps/user-web`：普通用户门户，用于自助查看资源、申请权限、执行被授权的运维动作。

### 普通用户控制台功能骨架

`apps/admin-web` 当前先按静态页面搭好以下侧边功能栏，后续再逐步接入真实 API：

- `机器信息管理`：下分 `环境 API 地址`、`机器账号列表`、`中间件账号获取` 三个子页面。环境 API 地址只给研发展示 CPU、内存、根目录磁盘、公网 IP、私网 IP、Loki 日志、K8S Pod 状态与事件的查询地址，不在该子页直接执行查询。
- `业务系统管理`：下分 `服务 NodePort`、`镜像 tag`、`GPU 模型显存`、`环境变量 key` 四个子页面。
- `中间件系统管理`：下分 `Nacos key 获取`、`数据库可用性校验` 两个子页面。Nacos key 后续由前端传环境和服务给后端，后端请求 Codex，再通过 skill 获取并隐藏 value 后返回 key；数据库校验后续由后端脚本执行。
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
