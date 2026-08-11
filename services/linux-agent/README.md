# Linux Account Agent

`linux-agent` 是部署在 Linux 主机上的只读账号采集服务。当前版本读取 `/etc/passwd` 和 `/etc/login.defs`，只返回普通用户 UID 范围内的人工账号，不读取 `/etc/shadow`，也不修改密码、Shell、用户组或账号状态。

## API

```text
GET /healthz   无鉴权健康检查
GET /v1/users  Bearer Token 鉴权，返回账号清单
```

账号清单包含用户名、UID、GID、备注、Home、Shell 和 Shell 登录能力。人工账号范围从 `/etc/login.defs` 的 `UID_MIN/UID_MAX` 获取；`root`、系统账号和软件服务账号均不进入业务管理列表。`login_enabled_count` 只表示 Shell 不是 `nologin`、`false` 等禁用 Shell，不代表密码或 SSH Key 一定可用。

## 构建

```bash
go test ./...
CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -trimpath -ldflags="-s -w" -o bin/linux-account-agent .
```

## 配置

| 环境变量 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `INFRAOPS_AGENT_TOKEN` | 是 | 无 | 至少 32 字符的 API Token |
| `INFRAOPS_AGENT_LISTEN` | 否 | `127.0.0.1:39110` | 监听地址 |
| `INFRAOPS_AGENT_PASSWD_FILE` | 否 | `/etc/passwd` | 账号文件路径，主要用于测试 |
| `INFRAOPS_AGENT_LOGIN_DEFS_FILE` | 否 | `/etc/login.defs` | 普通账号 UID 范围配置 |
| `INFRAOPS_AGENT_TLS_CERT_FILE` | 否 | 无 | TLS 证书；必须和私钥同时配置 |
| `INFRAOPS_AGENT_TLS_KEY_FILE` | 否 | 无 | TLS 私钥 |

示例：

```bash
export INFRAOPS_AGENT_TOKEN='replace-with-a-random-token-at-least-32-characters'
export INFRAOPS_AGENT_LISTEN='127.0.0.1:39110'
./bin/linux-account-agent
```

## systemd

生产部署应使用专用低权限账号运行，并将 Token 放在 root 可读的 EnvironmentFile 中。Agent 当前不需要 root 权限。

服务名：`infraops-linux-agent.service`

```ini
[Unit]
Description=AI InfraOps Linux Account Agent
After=network-online.target

[Service]
User=infraops-agent
Group=infraops-agent
EnvironmentFile=/etc/infraops/linux-account-agent.env
ExecStart=/data/tmp/user-golang/bin/linux-account-agent
Restart=on-failure
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true

[Install]
WantedBy=multi-user.target
```

常用管理命令：

```bash
systemctl status infraops-linux-agent
systemctl restart infraops-linux-agent
systemctl stop infraops-linux-agent
journalctl -u infraops-linux-agent -f
```

密码校验、密码同步和账号禁用后续由独立的受限 root helper 实现，Agent 不会增加任意 Shell 执行接口。
