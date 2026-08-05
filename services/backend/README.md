# Backend

AI InfraOps 后端服务。当前阶段使用 FastAPI + MySQL 实现 RBAC 基础能力：

- 登录
- 用户
- 角色
- 权限
- 菜单
- 机器资源信息
- 环境主机与 K8S 凭证登记
- K8S Namespace 与 NodePort 公网调用地址查询
- namespace 与 Running Pod 镜像查询
- 白名单 namespace 下 Pod 运行时环境变量 Key 查询

## Python 环境

使用本机 micromamba 的 `base` 环境，当前预期路径：

```text
D:\python-all-project
```

安装依赖：

```powershell
micromamba run -n base python -m pip install -r services/backend/requirements.txt
```

## 环境变量

仓库最外层的 `.env` 保存真实连接信息，已被 `.gitignore` 忽略；`.env.example` 只保留示例值。

```text
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_DATABASE=infraops
MYSQL_USER=root
MYSQL_PWD=change-me
_MYSQL_PWD=change-me
NEXT_PUBLIC_RBAC_API_BASE_URL=http://localhost:8000
```

Python 代码会通过 `python-dotenv` 自动读取仓库根目录 `.env`。

Redis 会话配置：

```text
REDIS_HOST=127.0.0.1
REDIS_PORT=6379
REDIS_PASSWORD=change-me
REDIS_DB=0
REDIS_TLS=false
SESSION_TTL_SECONDS=86400

K8S_CONNECT_TIMEOUT_SECONDS=5
K8S_READ_TIMEOUT_SECONDS=20
K8S_CREDENTIAL_ENCRYPTION_KEY=replace-with-base64-encoded-32-byte-key
MIDDLEWARE_CREDENTIAL_ENCRYPTION_KEY=replace-with-base64-encoded-32-byte-key
NACOS_CONNECT_TIMEOUT_SECONDS=5
NACOS_READ_TIMEOUT_SECONDS=15

LOG_LEVEL=INFO
LOG_DIR=.local/logs
LOG_FILE_MAX_BYTES=10485760
LOG_FILE_BACKUP_COUNT=5
```

## 初始化 MySQL

初始化脚本会读取 `sql/init.sql`，创建 `infraops` 数据库、RBAC 表和初始管理员。

```powershell
cd services/backend
micromamba run -n base python scripts/init_mysql.py
```

初始后台账号：

```text
admin / admin
```

## 启动服务

```powershell
cd services/backend
micromamba run -n base python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

## 当前 API

```text
GET  /health
POST /api/auth/login
POST /api/auth/session
POST /api/auth/logout
GET  /api/rbac/users
GET  /api/rbac/roles
GET  /api/rbac/permissions
GET  /api/rbac/menus
GET  /api/hosts
POST /api/hosts
PUT  /api/hosts/{host_id}
POST /api/hosts/{host_id}/probe
DELETE /api/hosts/{host_id}
GET  /api/hosts/{host_id}/metrics
GET  /api/environments
GET  /api/k8s/clusters
POST /api/k8s/clusters
DELETE /api/k8s/clusters/{cluster_id}
GET  /api/k8s/hosts
GET  /api/k8s/namespaces
GET  /api/k8s/images
GET  /api/k8s/nodeports/hosts
GET  /api/k8s/nodeports/namespaces
GET  /api/k8s/nodeports
GET  /api/k8s/env/hosts
GET  /api/k8s/env/namespaces
GET  /api/k8s/env/workloads
GET  /api/k8s/env/keys
GET  /api/middleware/instances
POST /api/middleware/instances
DELETE /api/middleware/instances/{instance_id}
GET  /api/nacos/instances
GET  /api/nacos/instances/{instance_id}/catalog
```

## Nacos 实例登记

`006_middleware_instances.sql` 创建 `middleware_instances`，每条实例通过 `environment_id` 关联 `infra_environments`。后台提交所属环境、Nacos URL、用户名和密码后，FastAPI 使用 AES-256-GCM 加密密码，只把密文和随机 nonce 写入 MySQL。

查询接口显式选择公开字段，不会返回 `password_ciphertext` 或 `password_nonce`。日志同样不记录请求体、用户名、密码和连接 URL。建议为 `MIDDLEWARE_CREDENTIAL_ENCRYPTION_KEY` 配置独立的 Base64 32 字节密钥；迁移期间未配置时，后端会从现有 K8S 密钥派生用途隔离的密钥。

中间件实例接口要求 `Authorization: Bearer <backend_admin_web access_token>`，并校验对应的 `middleware:*` 权限。

当前 `status=configured` 仅表示连接信息已保存，不代表 Nacos 已完成连通性验证。普通用户端使用 `user_web` Bearer 会话调用 `/api/nacos/instances` 获取环境选项，再调用 `/api/nacos/instances/{instance_id}/catalog` 实时查询目录；两个接口要求 `nacos:catalog:list` 权限。

Nacos adapter 当前使用 2.x 官方命名空间与配置目录接口，只返回 Namespace、Group、DataId 和格式。后端采用字段白名单映射，不返回连接地址、账号、密码、密文、nonce、配置正文或 MD5；目录查询成功后实例状态更新为 `active`，失败时更新为 `unreachable` 并保存脱敏后的故障说明。

冒烟检查会读取首个已登记 Nacos，只输出安全计数：

```powershell
cd services/backend
micromamba run -n base python scripts/check_nacos_catalog.py
```

## 机器资源信息

当前通过 node-exporter 采集：

- `node_cpu_seconds_total{cpu="...",mode="..."}`：通过短间隔采样计算 CPU 使用率，并统计 CPU 逻辑核数
- `node_memory_MemTotal_bytes`、`node_memory_MemFree_bytes`、`node_memory_MemAvailable_bytes`：近似 `free -h`
- `node_filesystem_size_bytes{mountpoint="/"}`
- `node_filesystem_avail_bytes{mountpoint="/"}`
- `node_uname_info`：主机 nodename

公网 IP 从 `node_exporter_url` 的 host 部分推断。私网 IP 暂时作为主机登记字段手动维护。

## 日志与连接诊断

FastAPI 使用标准库 `logging` 输出 JSON 结构化日志，同时写入控制台和仓库根目录的 `.local/logs/backend.log`。日志文件默认单文件 10 MiB，保留 5 个滚动文件；`.local` 已被 Git 忽略。

每个 HTTP 请求都会生成或透传 `X-Request-ID`，日志记录请求方法、路径、状态码和耗时，不记录请求体、密码或 kubeconfig。node-exporter 探测会区分连接超时、连接拒绝、DNS、HTTP 状态码、TLS 和 URL 格式错误，并将可读原因同步保存到 `machine_hosts.last_error`。

PowerShell 实时查看日志：

```powershell
Get-Content .local/logs/backend.log -Wait
```

后台主机列表会直接展示最近连接说明，也可以调用以下接口重新检测：

```text
POST /api/hosts/{host_id}/probe
```

## 登录会话

登录成功后会生成 opaque `access_token`，并以 `client_type` 维度写入 Redis：

```text
infraops:session:{client_type}:{access_token}
```

当前前端使用：

```text
user_web
backend_admin_web
```

因此普通用户控制台和后端管理页面的会话互相隔离。

## K8S 凭据

管理页面在主机表单中提供 kubeconfig 多行输入栏。提交后 FastAPI 校验 YAML 结构，使用 AES-256-GCM 加密并将密文、随机 nonce、SHA-256 指纹和文件名保存到 MySQL；凭证通过唯一 `host_id` 与主机关联，查询 K8S API 时只在内存中解密。编辑时凭证输入留空会保留原密文。`K8S_CREDENTIAL_ENCRYPTION_KEY` 必须是 Base64 编码的 32 字节随机密钥，只保存在根目录 `.env`。

kubeconfig 通常只有几 KB，使用 `MEDIUMBLOB` 存储不存在容量压力。需要重点保护的是 `.env` 中的主密钥，并在生产部署中通过 Secret/密钥管理系统注入。镜像查询只需要 namespace 和 Pod 的只读权限。环境变量 Key 查询还需要读取 Deployment、StatefulSet、ReplicaSet 和 Pod，并对 `pods/exec` 子资源执行 `create`。

后台主机记录的 `namespace_keys` 是普通用户环境变量查询白名单。四个 `/api/k8s/env/*` 接口均要求 `user_web` 会话和 `k8s:env:list` 权限，Namespace 参数在后端逐次校验，不能依赖前端筛选防越权。Exec 命令在容器内使用 NUL 分隔读取 `/proc/self/environ`，每条记录只输出 `=` 前的名称；后端不记录命令输出。没有 `/bin/sh`、`xargs` 或不可读取 procfs 的精简镜像会返回容器级错误，不影响其他容器。

KubeKey 集群的 API Server 证书通常签发给 kubeconfig 原始域名。需要把 `server` 改成可从平台访问的 IP 时，优先保留证书校验并添加原域名作为 TLS 校验名：

```yaml
clusters:
  - cluster:
      server: https://203.0.113.10:6443
      tls-server-name: original-api-server.example.internal
      certificate-authority-data: <原始 CA 数据>
```

如果无法使用证书内域名，可以只在受信网络中临时跳过校验：

```yaml
clusters:
  - cluster:
      server: https://203.0.113.10:6443
      insecure-skip-tls-verify: true
```

平台会遵循 kubeconfig 中的 `tls-server-name` 和 `insecure-skip-tls-verify`。跳过校验时仍然使用 HTTPS 和客户端凭证，只是不验证 API Server 身份，存在中间人攻击风险，不建议用于公网长期配置。
