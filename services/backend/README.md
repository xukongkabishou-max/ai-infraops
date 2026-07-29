# Backend

AI InfraOps 后端服务。当前阶段使用 FastAPI + MySQL 实现 RBAC 基础能力：

- 登录
- 用户
- 角色
- 权限
- 菜单
- 机器资源信息
- 环境主机与 K8S 凭证登记
- namespace 与 Running Pod 镜像查询

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
DELETE /api/hosts/{host_id}
GET  /api/hosts/{host_id}/metrics
GET  /api/environments
GET  /api/k8s/clusters
POST /api/k8s/clusters
DELETE /api/k8s/clusters/{cluster_id}
GET  /api/k8s/hosts
GET  /api/k8s/namespaces
GET  /api/k8s/images
```

## 机器资源信息

当前通过 node-exporter 采集：

- `node_cpu_seconds_total{cpu="...",mode="..."}`：通过短间隔采样计算 CPU 使用率，并统计 CPU 逻辑核数
- `node_memory_MemTotal_bytes`、`node_memory_MemFree_bytes`、`node_memory_MemAvailable_bytes`：近似 `free -h`
- `node_filesystem_size_bytes{mountpoint="/"}`
- `node_filesystem_avail_bytes{mountpoint="/"}`
- `node_uname_info`：主机 nodename

公网 IP 从 `node_exporter_url` 的 host 部分推断。私网 IP 暂时作为主机登记字段手动维护。

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

kubeconfig 通常只有几 KB，使用 `MEDIUMBLOB` 存储不存在容量压力。需要重点保护的是 `.env` 中的主密钥，并在生产部署中通过 Secret/密钥管理系统注入。当前查询只需要 namespace 和 Pod 的只读权限。
