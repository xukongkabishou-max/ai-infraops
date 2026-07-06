# npm 依赖存储迁移到 D 盘

本文记录将项目依赖、npm 全局模块和 npm 缓存放到 D 盘的命令。

## 项目位置

当前项目目标位置：

```text
D:\git\ai-infraops\ai-infraops
```

## npm 默认存储位置

建议使用这两个目录：

```text
D:\npm\global
D:\npm\cache
```

## 设置命令

把 npm 全局安装包位置改到 D 盘：

```powershell
npm config set prefix "D:\npm\global" --location=user
```

把 npm 缓存位置改到 D 盘：

```powershell
npm config set cache "D:\npm\cache" --location=user
```

查看是否生效：

```powershell
npm config get prefix
npm config get cache
npm root -g
```

预期输出类似：

```text
D:\npm\global
D:\npm\cache
D:\npm\global\node_modules
```

## PATH 提醒

如果安装全局命令后终端找不到命令，需要把下面路径加入用户环境变量 `Path`：

```text
D:\npm\global
```

PowerShell 临时生效命令：

```powershell
$env:Path = "D:\npm\global;$env:Path"
```

永久加入用户 Path 的 PowerShell 命令：

```powershell
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($userPath -notlike "*D:\npm\global*") {
  [Environment]::SetEnvironmentVariable("Path", "D:\npm\global;$userPath", "User")
}
```

修改用户环境变量后，需要重新打开终端。

## 项目依赖安装

项目迁移到 D 盘后，在项目根目录安装依赖：

```powershell
cd D:\git\ai-infraops\ai-infraops
npm install
```

启动管理端前端：

```powershell
npm run dev:admin
```
