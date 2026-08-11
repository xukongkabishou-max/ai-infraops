# Linux 主机账号采集 Agent

## 当前范围

每台需要接入账号清单的 Linux 主机运行一个低权限 Go Agent。平台后台在主机记录中维护 Agent 基础地址，FastAPI 使用服务端 Token 请求 Agent，普通用户页面只访问 FastAPI，不直连 Agent。

第一阶段只实现：

- 读取 `/etc/passwd` 和 `/etc/login.defs`。
- 只返回 `UID_MIN..UID_MAX` 普通用户范围内的人工账号。
- `root`、系统账号和软件服务账号不进入业务管理列表。
- 返回用户名、UID、GID、Home、Shell、备注和账号类型。
- Bearer Token 鉴权和可选 HTTPS。

第一阶段不读取 `/etc/shadow`，不修改密码，不锁定、解锁或删除账号。

## 调用链路

```text
用户页面
  -> GET /api/linux-accounts/hosts
  -> 选择所属环境和主机
  -> GET /api/linux-accounts/hosts/{host_id}
  -> FastAPI 读取 machine_hosts.linux_agent_url
  -> FastAPI 携带服务端 Bearer Token 请求 Agent /v1/users
  -> Agent 读取账号与发行版基线，过滤系统基础账号后返回结构化清单
```

Token 只存在于根目录 `.env` 和主机的 systemd EnvironmentFile，不能返回浏览器，也不能写入仓库。开发环境使用自签名 HTTPS 时可在本地关闭证书校验；生产环境必须使用受信 CA 或 mTLS。

## 后续扩展

密码哈希比对、密码同步和禁用账号应增加独立的受限 root helper。Go Agent 继续使用低权限账号运行，只允许调用固定动作，不提供任意命令执行接口。平台侧同时增加账号基线、哈希指纹、托管密码引用和操作审计表。
