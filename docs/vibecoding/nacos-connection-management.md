# Nacos 连接信息管理

## 当前实现

后台管理页面在“中间件资源信息 → 中间件实例”登记以下字段：

- 所属环境
- 实例名称
- Nacos URL
- 用户名
- 密码

`services/backend/sql/006_middleware_instances.sql` 创建 `middleware_instances`。所属环境复用 `infra_environments`，同一个 Nacos URL 不允许重复登记。当前提供列表、新增和删除接口，保存成功后的 `configured` 只表示凭证已经入库，不代表连接检测成功。

三个接口都要求携带 3001 管理端 `backend_admin_web` 会话的 Bearer Token，并分别校验 `middleware:list`、`middleware:create`、`middleware:delete` 权限。

## 凭证处理

密码使用 AES-256-GCM 加密，MySQL 只保存密文和 12 字节随机 nonce。管理列表接口显式排除这两个字段，前端只能看到“已加密”状态，不能读取密码。

优先在根目录 `.env` 设置独立的 `MIDDLEWARE_CREDENTIAL_ENCRYPTION_KEY`。迁移期间未设置时，后端会通过 HKDF 从现有 K8S 凭证密钥派生独立用途密钥。后续补充独立密钥时，解密过程仍会兼容此前使用派生密钥保存的记录；两类凭证使用不同 AAD，不能互相解密。

## API

```text
GET    /api/middleware/instances?middleware_type=nacos
POST   /api/middleware/instances
DELETE /api/middleware/instances/{instance_id}
GET    /api/nacos/instances
GET    /api/nacos/instances/{instance_id}/catalog
POST   /api/nacos/instances/{instance_id}/config-structure
```

新增请求：

```json
{
  "middleware_type": "nacos",
  "environment_name": "示例环境",
  "instance_name": "示例环境 Nacos",
  "base_url": "http://nacos.example.internal:8848/nacos",
  "username": "example-user",
  "password": "<仅在请求中提交>"
}
```

## 普通用户端目录链路

普通用户页面从 `/api/nacos/instances` 拉取后台已登记的环境，再由按钮请求 `/api/nacos/instances/{instance_id}/catalog`。这两个接口只接受 `user_web` Bearer 会话，并校验 `nacos:catalog:list` 权限；环境选项不包含 Nacos URL、用户名或任何密码字段。

页面将 Namespace 作为可横向滚动的标签栏排列，标签显示各自配置数量；切换标签后，下方只渲染当前 Namespace 的 Group、DataId 和格式表格，避免多个大型配置表纵向堆叠。

当前 Nacos adapter 使用 2.x 官方接口：

```text
GET /nacos/v2/console/namespace/list
GET /nacos/v2/cs/history/configs?namespaceId=...
```

配置目录接口中只有 `dataId`、`group`、`tenant`、`appName` 和 `type` 属于有效元数据。FastAPI 进一步使用字段白名单，只向前端返回 Namespace、Group、DataId 和格式；`content`、MD5、连接凭证及未知字段都会被丢弃。查询成功后实例状态更新为 `active`，连接或鉴权失败时更新为 `unreachable`，错误说明不包含 URL、账号、令牌或响应正文。

每条 YAML、YML 或 JSON 配置右侧都有“查看内容”按钮。点击后，前端通过 `config-structure` 接口提交 Namespace、Group、DataId 和格式，并在该配置行的正下方展示加载状态或脱敏结果；行内操作和结果标题栏都提供“收起”按钮。切换环境、Namespace 或快速点选其他配置时，旧请求结果不会覆盖当前展开项。

FastAPI 只在服务端内存中读取被点击的这一份配置。JSON 使用标准库解析后递归把所有叶子 value 替换为 `null`，保持为合法 JSON。YAML 使用 PyYAML 解析语法树，但不重新序列化：后端根据叶子节点在原文中的起止位置原位清空 value，因此原始缩进、空行、列表层级和换行顺序保持不变；注释文本也会清空，避免注释携带敏感信息。

原始正文不会写入 MySQL、日志或 API 响应。接口限制正文最大 1 MB；解析错误只返回格式错误说明，不拼接原文或异常附近内容。当前不支持 Properties、TOML 和普通文本，前端会将这些格式显示为不可点击状态。

可使用以下脚本做安全冒烟检查，输出只有数量：

```powershell
cd services/backend
micromamba run -n base python scripts/check_nacos_catalog.py
```

## 后续链路

后续再按实际配置类型补 Properties 和 TOML 的确定性解析器。大模型不持有 Nacos 凭证，只在确定性解析器无法处理的格式上作为受控兜底。
