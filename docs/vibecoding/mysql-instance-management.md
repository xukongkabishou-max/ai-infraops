# MySQL 实例管理

## 当前范围

后台管理页面的“中间件资源信息 → 中间件实例”新增 MySQL 类型，登记以下信息：

- 所属环境
- 实例名称
- MySQL Host 和连接端口
- 管理用户名和管理密码
- Grafana 仪表盘地址

普通用户控制台已支持按数据库类型、所属环境和实例查询 MySQL 账号。超级管理员可以登记当前密码、显示或复制托管密码、对比 MySQL 实际密码，并在不一致时将输入密码同步到 MySQL。中间件系统页面会在 MySQL 卡片中列出已登记的 Grafana 仪表盘链接，点击后在新窗口打开。

已登记的 Nacos、Doris 和 MySQL 实例均可在后台点击“编辑”。环境、实例名称、连接地址、用户名和仪表盘地址会回填；密码明文不会回显，留空提交时沿用原密文，填写新密码时才重新加密覆盖。

## 数据设计

MySQL 继续使用 `middleware_instances`：

- `middleware_type=mysql`
- `base_url=mysql://host:port`
- `username` 保存管理用户名
- `password_ciphertext`、`password_nonce` 保存 AES-256-GCM 加密凭证
- `dashboard_url` 保存完整的 HTTP/HTTPS Grafana 仪表盘地址，允许保留 Grafana 查询参数

`services/backend/sql/016_mysql_dashboard.sql` 以幂等方式给已有实例表增加 `dashboard_url`，并创建 `middleware:update` 与 `mysql:dashboard:view` 权限。旧 `exporter_url` 列暂时保留用于历史兼容，不再由管理页面读写。`dashboard_url` 对 Nacos 和 Doris 为空；创建或更新 MySQL 实例时，API 会强制要求填写 HTTP/HTTPS 地址并拒绝 URL 内嵌用户名或密码。

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
PUT    /api/middleware/instances/{instance_id}
DELETE /api/middleware/instances/{instance_id}

GET  /api/mysql/dashboards
GET  /api/mysql/instances
GET  /api/mysql/instances/{instance_id}/accounts
POST /api/mysql/instances/{instance_id}/accounts/password/verify
PUT  /api/mysql/instances/{instance_id}/accounts/password
POST /api/mysql/instances/{instance_id}/accounts/password/current
PUT  /api/mysql/instances/{instance_id}/accounts/password/current
```

中间件实例接口只接受后台管理会话并校验 `middleware:*` 权限。更新操作要求 `middleware:update`，授予 `super_admin` 和 `ops`。MySQL 账号列表接口要求普通用户端会话和 `mysql:accounts:list` 权限；密码托管、显示、复制、校验和同步功能额外要求 `isSuperuser=true`。日志不记录请求体和密码。

`GET /api/mysql/dashboards` 使用独立的 `mysql:dashboard:view` 权限，并授予 `super_admin`、`ops` 和 `rd`。响应只包含环境、实例名称、仪表盘地址和接入状态，不包含 `base_url`、管理用户名、密码密文或 nonce，避免为了查看仪表盘扩大账号盘点权限。

“当前密码”不是从 MySQL 哈希反解得到，而是平台手工登记、校验成功或同步修改后保存的已知密码。该密码使用独立 AAD 的 AES-256-GCM 密文保存在 `mysql_account_credentials`，显示、复制、手工登记、校验和同步事件写入 `mysql_account_credential_audit`，审计记录不保存密码。

密码对比由目标账号直接连接 MySQL 后校验 `CURRENT_USER()` 是否与选择的 `'username'@'host'` 完全一致。同步密码由登记管理账号执行参数化的 `ALTER USER ... IDENTIFIED BY`，因此管理账号需要对应权限。

用户端不内嵌或代理 Grafana。MySQL 卡片按“所属环境 / 实例名称”列出原始仪表盘 URL，点击后在新窗口打开，因此可直接兼容仅有 IP 和 HTTP 的 Grafana，也不会遇到 iframe 第三方 Cookie 导致的登录循环。Grafana 登录、匿名访问和仪表盘自身的数据权限仍由 Grafana 管理，本平台不保存或代填其登录凭证。
