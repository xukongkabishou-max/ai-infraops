# MySQL 实例管理

## 当前范围

后台管理页面的“中间件资源信息 → 中间件实例”新增 MySQL 类型，登记以下信息：

- 所属环境
- 实例名称
- MySQL Host 和连接端口
- 管理用户名和管理密码
- mysql-exporter URL

普通用户控制台已支持按数据库类型、所属环境和实例查询 MySQL 账号。超级管理员可以登记当前密码、显示或复制托管密码、对比 MySQL 实际密码，并在不一致时将输入密码同步到 MySQL。mysql-exporter 指标展示和权限管理仍留待后续实现。

## 数据设计

MySQL 继续使用 `middleware_instances`：

- `middleware_type=mysql`
- `base_url=mysql://host:port`
- `username` 保存管理用户名
- `password_ciphertext`、`password_nonce` 保存 AES-256-GCM 加密凭证
- `exporter_url` 保存完整的 HTTP/HTTPS mysql-exporter 指标地址

`services/backend/sql/012_mysql_instances.sql` 以幂等方式给已有实例表增加 `exporter_url`。该字段允许为空，是为了兼容已经登记的 Nacos 和 Doris；创建 MySQL 实例时，API 会强制要求填写并校验地址。

## 账号数据

账号盘点使用登记管理账号连接 MySQL，并查询 `mysql.user` 的以下白名单字段：

- `User`
- `Host`
- `plugin`
- `account_locked`
- `password_expired`

后端不会查询或返回 `authentication_string` 等密码哈希字段。账号接口返回规范化的 `'username'@'host'` 标识、认证插件和锁定/过期状态；登记管理账号需要具备读取 `mysql.user` 的权限。

## API 边界

```text
GET    /api/middleware/instances
POST   /api/middleware/instances
DELETE /api/middleware/instances/{instance_id}

GET  /api/mysql/instances
GET  /api/mysql/instances/{instance_id}/accounts
POST /api/mysql/instances/{instance_id}/accounts/password/verify
PUT  /api/mysql/instances/{instance_id}/accounts/password
POST /api/mysql/instances/{instance_id}/accounts/password/current
PUT  /api/mysql/instances/{instance_id}/accounts/password/current
```

中间件实例接口只接受后台管理会话并校验 `middleware:*` 权限。MySQL 账号列表接口要求普通用户端会话和 `mysql:accounts:list` 权限；密码托管、显示、复制、校验和同步功能额外要求 `isSuperuser=true`。列表允许返回连接地址、管理用户名和 Exporter 地址，不查询或返回密码密文与 nonce。日志不记录请求体和密码。

“当前密码”不是从 MySQL 哈希反解得到，而是平台手工登记、校验成功或同步修改后保存的已知密码。该密码使用独立 AAD 的 AES-256-GCM 密文保存在 `mysql_account_credentials`，显示、复制、手工登记、校验和同步事件写入 `mysql_account_credential_audit`，审计记录不保存密码。

密码对比由目标账号直接连接 MySQL 后校验 `CURRENT_USER()` 是否与选择的 `'username'@'host'` 完全一致。同步密码由登记管理账号执行参数化的 `ALTER USER ... IDENTIFIED BY`，因此管理账号需要对应权限。

后续指标接口应由 FastAPI 请求 mysql-exporter，并只把白名单指标返回普通用户页面；浏览器不直接访问 exporter。指标采集与账号盘点继续分开授权。
