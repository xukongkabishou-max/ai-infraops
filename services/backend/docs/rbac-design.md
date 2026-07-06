# RBAC 设计草案

当前只覆盖平台第一阶段需要的五个能力：

```text
登录
用户
角色
权限
菜单
机器资源信息
```

## 技术选择

第一阶段使用 FastAPI + PyMySQL + MySQL。原因是：

- FastAPI 轻量，适合快速做接口和自动化脚本 API。
- MySQL 适合 RBAC 这种关系清晰、需要唯一约束和关联表的数据。
- 后续如果要接 Kubernetes API、各类中间件用户权限 API，可以继续在 Python 服务里扩展。

## 实体

### User

用户表 `rbac_users` 独立维护平台后台账号。当前初始化一个超级管理员：

```text
admin / admin
```

密码只保存 bcrypt hash，不保存明文。

### Role

角色表示一组权限集合，例如：

- 超级管理员
- 运维负责人
- 只读观察员

当前初始化 `super_admin`。

### Permission

权限点使用稳定编码表示：

```text
user:list
user:create
role:list
role:update
permission:list
menu:list
menu:publish
```

权限类型分为：

- `api`：接口权限
- `page`：页面权限
- `button`：按钮权限
- `data`：数据权限

### Menu

菜单绑定权限点。前端拿到菜单列表后，只展示当前用户有权限访问的菜单。

## API 前缀

```text
/api/auth/
/api/rbac/
```

## 初始化 SQL

源码位置：

```text
services/backend/sql/init.sql
```

执行方式：

```powershell
cd services/backend
micromamba run -n base python scripts/init_mysql.py
```

## 后续演进

- 增加真实 JWT 签发和刷新
- 增加操作审计
- 增加菜单树递归接口
- 增加当前用户信息接口 `/api/auth/me`
- 增加基于角色的菜单过滤和按钮级权限
