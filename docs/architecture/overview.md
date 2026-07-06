# 架构总览

AI InfraOps 采用 monorepo 结构，前端、后端服务、共享包、基础设施配置和项目文档统一放在一个仓库中。

## 前端

- `apps/admin-web`：后台管理人员控制面板，用于平台管理、权限配置、资源编排、告警处理和可观测性。
- `apps/user-web`：普通用户门户，用于自助查看资源、申请权限、执行被授权的运维动作。

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
