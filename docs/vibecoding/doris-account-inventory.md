# Doris 账号信息查询

## 数据关系

Doris 与 Nacos 复用 `middleware_instances`。后台登记时保存：

- `environment_id`：关联 `infra_environments`
- `middleware_type=doris`
- 实例名称
- FE Host 与查询端口
- 管理用户名
- AES-256-GCM 加密后的密码密文和随机 nonce

数据库不保存账号查询快照。用户每次点击“获取账号列表”时，FastAPI 才连接对应 Doris 实例实时查询。超级管理员主动托管的已发放密码单独保存在 `doris_account_credentials`，不与实时账号查询结果混在一起。

## API 链路

```text
后台管理页面
  POST /api/middleware/instances
          ↓
middleware_instances
          ↓
用户页面选择所属环境和 Doris 实例
          ↓
  GET /api/doris/instances/{id}/accounts
          ↓
Doris FE MySQL 查询端口
          ↓
  SHOW ALL GRANTS
```

用户端接口使用 `user_web` Bearer 会话并校验 `doris:accounts:list`。环境和实例列表不返回 FE 地址、登记用户名或凭据字段。

超级管理员还可以使用以下接口校验和同步已发放密码：

```text
POST /api/doris/instances/{id}/accounts/password/verify
PUT  /api/doris/instances/{id}/accounts/password
POST /api/doris/instances/{id}/accounts/password/current
PUT  /api/doris/instances/{id}/accounts/password/current
```

两个接口都在服务端强制校验 `isSuperuser`，不能依赖前端隐藏按钮作为权限边界。

## 返回字段

Doris 官方 `SHOW ALL GRANTS` 返回用户标识、备注、Password 状态、角色以及全局、Catalog、数据库、表、列、资源和 Workload Group 等权限列。平台只返回：

- 用户名与 Host
- 原始 `UserIdentity`
- 备注
- 角色
- 非空权限范围

适配器显式丢弃 `Password`、`password_hash`、`authentication_string` 等认证字段。Doris 不保存可逆明文密码，因此平台无法从 Doris 反解已有账号密码；“当前密码”只代表平台此前校验或同步成功后托管的已发放密码。

## 密码对比与同步

Doris 的系统表不提供可用于外部逐项比较的真实密码哈希。页面中的“密码对比”采用 Doris 原生认证：后端使用超级管理员输入的候选密码尝试以目标用户连接 FE，再执行 `SELECT CURRENT_USER()`，只有认证成功且实际命中的 `用户名@Host` 与目标账号完全一致时才返回“密码一致”。

错误候选密码不保存。候选密码校验成功后，或超级管理员同步修改成功后，平台才使用独立 AES-256-GCM 上下文加密并更新 `doris_account_credentials`。输入变化后前端会清除上次结果；只有明确得到“不一致”结果时，才允许超级管理员使用登记的 Doris 管理凭证执行 `SET PASSWORD FOR ... = PASSWORD(...)`。Doris 仍会执行原生权限检查，登记账号需要 `ADMIN_PRIV`，`root` 账号的修改限制也由 Doris 自身执行。

“当前密码”支持超级管理员直接输入并手工保存，这一步只更新平台密文，不连接或修改 Doris；右侧“密码对比”用于另行确认登记值是否与 Doris 实际认证一致。已登记密码默认隐藏，点击显示或复制时，前端才调用 `/password/current` 单独读取；响应设置 `Cache-Control: no-store`，密码不写日志。生产部署必须使用 HTTPS，避免凭证在网络中以明文传输。

`doris_account_credential_audit` 不保存密码，只记录实例、用户标识、操作人、时间以及以下动作：

- 校验成功并托管
- 同步修改密码
- 手工登记或更新当前密码
- 查看当前密码
- 复制当前密码

平台只保留当前有效密码，不保留旧密码历史副本。

每次对比都会产生一次真实认证请求。若 Doris 开启失败登录锁定策略，连续输入错误密码可能触发账号锁定，因此页面不会自动重试。

## 权限要求

登记到平台的 Doris 管理账号需要 `GRANT_PRIV` 才能执行 `SHOW ALL GRANTS` 查看全部用户授权；权限不足时接口返回脱敏错误，并把实例状态更新为 `unreachable`。日志只记录实例 ID、结果数量和异常类型，不记录 FE 地址、用户名、密码或 SQL 返回内容。

## 前辈经验

- [Apache Doris SHOW GRANTS](https://doris.apache.org/docs/4.x/sql-manual/sql-statements/account-management/SHOW-GRANTS/)：`SHOW ALL GRANTS` 的语法、返回列和 `GRANT_PRIV` 要求。
- [Apache Doris SET PASSWORD](https://doris.apache.org/docs/4.x/sql-manual/sql-statements/account-management/SET-PASSWORD/)：密码修改语法、`ADMIN_PRIV` 和 `root` 账号限制。
- [Apache Doris mysql.user](https://doris.apache.org/docs/dev/admin-manual/system-tables/mysql/user/)：兼容系统表中的 `authentication_string` 始终为空。
- [Apache Doris Authentication and Authorization](https://doris.apache.org/docs/4.x/admin-manual/auth/authentication-and-authorization/)：Doris 用户身份、RBAC 模型和账号管理边界。
