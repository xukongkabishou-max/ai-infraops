"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

type ApiUser = {
  id: number;
  username: string;
  displayName?: string;
  display_name?: string;
  email?: string;
  is_active?: boolean;
  last_login_at?: string | null;
};

type ApiRole = {
  id?: number;
  code: string;
  name?: string;
  description?: string | null;
};

type ApiPermission = {
  id?: number;
  code: string;
  name?: string;
};

type ApiMenu = {
  id: number;
  title: string;
  code: string;
  path: string;
};

type HostRecord = {
  id: number;
  environment_id?: number | null;
  environment_code?: string | null;
  environment_name?: string | null;
  hostname: string;
  public_ip: string;
  private_ip: string;
  node_exporter_url: string;
  namespace_keys?: string[];
  status: "active" | "unreachable";
  has_k8s_credential?: boolean | number;
  last_error?: string | null;
  last_seen_at?: string | null;
};

type LoginResponse = {
  access_token: string;
  user: ApiUser;
  roles: string[];
  permissions: string[];
  menus: ApiMenu[];
};

type HostNotice = {
  tone: "success" | "warning";
  message: string;
};

type MiddlewareInstance = {
  id: number;
  environment_name: string;
  middleware_type: string;
  instance_name: string;
  base_url: string;
  username: string;
  status: "configured" | "active" | "unreachable" | "disabled";
  credential_configured: boolean | number;
  last_error?: string | null;
  last_seen_at?: string | null;
  created_at: string;
};

const apiBaseUrl =
  process.env.NEXT_PUBLIC_RBAC_API_BASE_URL ?? "http://localhost:8000";
const backendAdminSessionStorageKey = "ai-infraops:backend-admin-web-session";
const backendAdminClientType = "backend_admin_web";

const navItems = [
  "总览",
  "用户管理",
  "角色管理",
  "权限管理",
  "菜单管理",
  "机器资源信息",
  "中间件资源信息",
];

const fallbackUsers: ApiUser[] = [
  { id: 1, username: "admin", displayName: "系统管理员", is_active: true },
];

export default function BackendAdminHome() {
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("admin");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [session, setSession] = useState<LoginResponse | null>(null);
  const [activeNav, setActiveNav] = useState("总览");
  const [users, setUsers] = useState<ApiUser[]>(fallbackUsers);
  const [roles, setRoles] = useState<ApiRole[]>([]);
  const [permissions, setPermissions] = useState<ApiPermission[]>([]);
  const [menus, setMenus] = useState<ApiMenu[]>([]);
  const [hosts, setHosts] = useState<HostRecord[]>([]);
  const [hostUrl, setHostUrl] = useState("");
  const [hostName, setHostName] = useState("");
  const [publicIp, setPublicIp] = useState("");
  const [privateIp, setPrivateIp] = useState("");
  const [environmentName, setEnvironmentName] = useState("");
  const [namespaceKeysText, setNamespaceKeysText] = useState("");
  const [k8sCredentialContent, setK8sCredentialContent] = useState("");
  const [editingHostId, setEditingHostId] = useState<number | null>(null);
  const [hostError, setHostError] = useState("");
  const [hostNotice, setHostNotice] = useState<HostNotice | null>(null);
  const [hostSaving, setHostSaving] = useState(false);
  const [probingHostId, setProbingHostId] = useState<number | null>(null);

  const metrics = useMemo(
    () => [
      { label: "用户总数", value: users.length || 1, hint: "来自 RBAC 用户表" },
      { label: "角色数量", value: roles.length || session?.roles.length || 0, hint: "角色集合" },
      {
        label: "权限点",
        value: permissions.length || session?.permissions.length || 0,
        hint: "API / 页面 / 按钮",
      },
      { label: "菜单节点", value: menus.length || session?.menus.length || 0, hint: "后台菜单配置" },
    ],
    [menus.length, permissions.length, roles.length, session, users.length],
  );

  useEffect(() => {
    let alive = true;
    const savedSession = readBackendAdminSession();
    if (!savedSession) {
      return;
    }

    fetch(`${apiBaseUrl}/api/auth/session`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(savedSession),
    })
      .then((response) => {
        if (!response.ok) {
          throw new Error("会话已失效");
        }
        return response.json() as Promise<LoginResponse>;
      })
      .then((loginData) => {
        if (!alive) {
          return;
        }
        applySession(loginData);
        window.localStorage.setItem(
          backendAdminSessionStorageKey,
          JSON.stringify({
            access_token: loginData.access_token,
            client_type: backendAdminClientType,
          }),
        );
        return Promise.all([
          fetchJson<ApiUser[]>("/api/rbac/users"),
          fetchJson<ApiRole[]>("/api/rbac/roles"),
          fetchJson<ApiPermission[]>("/api/rbac/permissions"),
          fetchJson<ApiMenu[]>("/api/rbac/menus"),
          fetchJson<HostRecord[]>("/api/hosts"),
        ]);
      })
      .then((rows) => {
        if (!rows || !alive) {
          return;
        }
        const [userRows, roleRows, permissionRows, menuRows, hostRows] = rows;
        setUsers(userRows);
        setRoles(roleRows);
        setPermissions(permissionRows);
        setMenus(menuRows);
        setHosts(hostRows);
      })
      .catch(() => {
        window.localStorage.removeItem(backendAdminSessionStorageKey);
        if (alive) {
          setSession(null);
        }
      });

    return () => {
      alive = false;
    };
  }, []);

  async function fetchJson<T>(path: string): Promise<T> {
    const response = await fetch(`${apiBaseUrl}${path}`);
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.detail ?? `接口请求失败：${path}`);
    }
    return response.json() as Promise<T>;
  }

  async function loadHosts() {
    const rows = await fetchJson<HostRecord[]>("/api/hosts");
    setHosts(rows);
  }

  function applySession(loginData: LoginResponse) {
    setSession(loginData);
    setUsers([loginData.user]);
    setRoles(loginData.roles.map((code) => ({ code, name: code })));
    setPermissions(loginData.permissions.map((code) => ({ code, name: code })));
    setMenus(loginData.menus);
  }

  async function handleLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError("");

    try {
      const response = await fetch(`${apiBaseUrl}/api/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password, client_type: backendAdminClientType }),
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail ?? "登录失败，请检查账号或密码");
      }

      const loginData = data as LoginResponse;
      applySession(loginData);
      window.localStorage.setItem(
        backendAdminSessionStorageKey,
        JSON.stringify({
          access_token: loginData.access_token,
          client_type: backendAdminClientType,
        }),
      );

      const [userRows, roleRows, permissionRows, menuRows, hostRows] = await Promise.all([
        fetchJson<ApiUser[]>("/api/rbac/users"),
        fetchJson<ApiRole[]>("/api/rbac/roles"),
        fetchJson<ApiPermission[]>("/api/rbac/permissions"),
        fetchJson<ApiMenu[]>("/api/rbac/menus"),
        fetchJson<HostRecord[]>("/api/hosts"),
      ]);
      setUsers(userRows);
      setRoles(roleRows);
      setPermissions(permissionRows);
      setMenus(menuRows);
      setHosts(hostRows);
    } catch (loginError) {
      setError(loginError instanceof Error ? loginError.message : "登录失败");
    } finally {
      setLoading(false);
    }
  }

  async function handleSaveHost(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setHostSaving(true);
    setHostError("");
    setHostNotice(null);

    try {
      const response = await fetch(`${apiBaseUrl}/api/hosts${editingHostId ? `/${editingHostId}` : ""}`, {
        method: editingHostId ? "PUT" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          node_exporter_url: hostUrl,
          hostname: hostName,
          public_ip: publicIp,
          private_ip: privateIp,
          environment_name: environmentName,
          namespace_keys: parseNamespaceKeys(namespaceKeysText),
          k8s_credential_name: k8sCredentialContent ? `${hostName}.yaml` : "",
          k8s_credential_content: k8sCredentialContent,
        }),
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail ?? `${editingHostId ? "更新" : "添加"}主机失败`);
      }
      const savedHost = data as HostRecord;
      resetHostForm();
      await loadHosts();
      setHostNotice({
        tone: savedHost.status === "active" ? "success" : "warning",
        message:
          savedHost.status === "active"
            ? `主机 ${savedHost.hostname} 已保存，node-exporter 连接正常。`
            : `主机已保存，但 node-exporter 检测失败：${savedHost.last_error ?? "未返回详细原因"}`,
      });
    } catch (saveError) {
      setHostError(saveError instanceof Error ? saveError.message : "保存主机失败");
    } finally {
      setHostSaving(false);
    }
  }

  function resetHostForm() {
    setEditingHostId(null);
    setHostUrl("");
    setHostName("");
    setPublicIp("");
    setPrivateIp("");
    setEnvironmentName("");
    setNamespaceKeysText("");
    setK8sCredentialContent("");
  }

  function handleEditHost(host: HostRecord) {
    setEditingHostId(host.id);
    setHostUrl(host.node_exporter_url);
    setHostName(host.hostname);
    setPublicIp(host.public_ip);
    setPrivateIp(host.private_ip);
    setEnvironmentName(host.environment_name ?? "");
    setNamespaceKeysText((host.namespace_keys ?? []).join(", "));
    setK8sCredentialContent("");
    setHostError("");
    setHostNotice(null);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  async function handleProbeHost(hostId: number) {
    setHostError("");
    setHostNotice(null);
    setProbingHostId(hostId);
    try {
      const response = await fetch(`${apiBaseUrl}/api/hosts/${hostId}/probe`, {
        method: "POST",
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data.detail ?? "重新检测主机失败");
      }
      const host = data as HostRecord;
      setHosts((currentHosts) =>
        currentHosts.map((currentHost) => (currentHost.id === host.id ? host : currentHost)),
      );
      setHostNotice({
        tone: host.status === "active" ? "success" : "warning",
        message:
          host.status === "active"
            ? `主机 ${host.hostname} 连接正常。`
            : `主机 ${host.hostname} 仍无法连接：${host.last_error ?? "未返回详细原因"}`,
      });
    } catch (probeError) {
      setHostError(probeError instanceof Error ? probeError.message : "重新检测主机失败");
    } finally {
      setProbingHostId(null);
    }
  }

  async function handleDeleteHost(hostId: number) {
    setHostError("");
    setHostNotice(null);
    const response = await fetch(`${apiBaseUrl}/api/hosts/${hostId}`, {
      method: "DELETE",
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      setHostError(data.detail ?? "删除主机失败");
      return;
    }
    await loadHosts();
  }

  function handleLogout() {
    const savedSession = readBackendAdminSession();
    if (savedSession) {
      fetch(`${apiBaseUrl}/api/auth/logout`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(savedSession),
      }).catch(() => undefined);
    }
    window.localStorage.removeItem(backendAdminSessionStorageKey);
    setSession(null);
    setActiveNav("总览");
  }

  if (!session) {
    return (
      <main className="grid min-h-screen place-items-center bg-[radial-gradient(circle_at_25%_10%,rgba(10,26,225,0.36),transparent_30%),linear-gradient(135deg,#04050b_0%,#050e58_100%)] px-5 text-white">
        <section className="w-full max-w-[460px]">
          <div className="mb-10 flex items-center gap-3">
            <div className="grid h-11 w-11 place-items-center rounded-[6px] bg-[#0a1ae1] font-black shadow-[0_0_38px_rgba(10,26,225,0.55)]">
              AI
            </div>
            <div>
              <p className="text-sm text-[#bfc9e7]/80">InfraOps</p>
              <p className="text-xs text-[#7f91ff]">后端 RBAC 管理</p>
            </div>
          </div>

          <p className="text-sm font-bold text-[#4b5fc6]">管理入口</p>
          <h1 className="mt-4 text-5xl font-black leading-tight tracking-normal">
            登录后管理用户、角色、权限与菜单。
          </h1>
          <p className="mt-5 text-base leading-8 text-[#bfc9e7]">
            使用 FastAPI 连接 MySQL 校验账号密码。初始化管理员账号为 admin。
          </p>

          <form className="mt-10 space-y-5" onSubmit={handleLogin}>
            <label className="block">
              <span className="text-sm font-bold text-[#bfc9e7]">管理员账号</span>
              <input
                className="mt-2 h-14 w-full rounded-[6px] border border-[#1b2fb0] bg-[#070b1b] px-4 text-base text-white outline-none transition placeholder:text-[#bfc9e7]/44 focus:border-[#7f91ff]"
                onChange={(event) => setUsername(event.target.value)}
                value={username}
              />
            </label>
            <label className="block">
              <span className="text-sm font-bold text-[#bfc9e7]">登录密码</span>
              <input
                className="mt-2 h-14 w-full rounded-[6px] border border-[#1b2fb0] bg-[#070b1b] px-4 text-base text-white outline-none transition placeholder:text-[#bfc9e7]/44 focus:border-[#7f91ff]"
                onChange={(event) => setPassword(event.target.value)}
                type="password"
                value={password}
              />
            </label>

            {error ? (
              <p className="rounded-[6px] border border-[#ff4d5d]/40 bg-[#a30613]/18 px-4 py-3 text-sm text-[#ff9aa3]">
                {error}
              </p>
            ) : null}

            <button
              className="h-14 w-full rounded-[6px] bg-[#0a1ae1] text-sm font-black text-white transition hover:bg-[#1628ff] disabled:cursor-not-allowed disabled:opacity-60"
              disabled={loading}
              type="submit"
            >
              {loading ? "正在校验..." : "进入管理后台"}
            </button>
          </form>
        </section>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-[#04050b] text-white">
      <div className="grid min-h-screen lg:grid-cols-[256px_1fr]">
        <aside className="border-r border-[#1b255d] bg-[#070b1b] px-5 py-6">
          <div className="mb-10 flex items-center gap-3">
            <div className="grid h-11 w-11 place-items-center rounded-[6px] bg-[#0a1ae1] font-black shadow-[0_0_38px_rgba(10,26,225,0.55)]">
              AI
            </div>
            <div>
              <p className="text-sm text-[#bfc9e7]/80">InfraOps</p>
              <p className="text-xs text-[#4b5fc6]">后端 RBAC 管理</p>
            </div>
          </div>

          <nav className="space-y-2">
            {navItems.map((item) => (
              <button
                className={`h-11 w-full rounded-[6px] px-4 text-left text-sm transition ${
                  activeNav === item
                    ? "bg-[#0a1ae1] font-bold text-white shadow-[0_12px_30px_rgba(10,26,225,0.28)]"
                    : "text-[#bfc9e7]/72 hover:bg-[#11183c] hover:text-white"
                }`}
                key={item}
                onClick={() => setActiveNav(item)}
                type="button"
              >
                {item}
              </button>
            ))}
          </nav>
        </aside>

        <section className="min-w-0 bg-[radial-gradient(circle_at_75%_5%,rgba(10,26,225,0.32),transparent_30%),linear-gradient(135deg,#04050b_0%,#050e58_100%)]">
          <header className="flex flex-wrap items-center justify-between gap-4 border-b border-white/10 px-6 py-5 lg:px-8">
            <div>
              <p className="text-sm font-semibold text-[#4b5fc6]">{activeNav}</p>
              <h1 className="mt-1 text-2xl font-black tracking-normal text-white">
                {activeNav === "机器资源信息"
                  ? "添加、删除与检查环境主机"
                  : activeNav === "中间件资源信息"
                    ? "维护中间件实例、账号与权限"
                    : "登录、用户、角色、权限、菜单"}
              </h1>
            </div>
            <div className="flex items-center gap-3">
              <span className="rounded-[5px] border border-[#4b5fc6] px-3 py-2 text-xs font-bold text-[#bfc9e7]">
                当前账号：{session.user.displayName ?? session.user.username}
              </span>
              <button
                className="h-10 rounded-[6px] bg-[#0a1ae1] px-4 text-sm font-bold text-white transition hover:bg-[#1628ff]"
                onClick={handleLogout}
                type="button"
              >
                退出登录
              </button>
            </div>
          </header>

          <div className="space-y-6 px-6 py-6 lg:px-8">
            {activeNav === "机器资源信息" ? (
              <MachineHostManager
                environmentName={environmentName}
                editingHostId={editingHostId}
                hostError={hostError}
                hostNotice={hostNotice}
                hostName={hostName}
                hostSaving={hostSaving}
                hostUrl={hostUrl}
                hosts={hosts}
                privateIp={privateIp}
                publicIp={publicIp}
                k8sCredentialContent={k8sCredentialContent}
                namespaceKeysText={namespaceKeysText}
                onCancelEdit={resetHostForm}
                onEditHost={handleEditHost}
                onProbeHost={handleProbeHost}
                onSaveHost={handleSaveHost}
                onDeleteHost={handleDeleteHost}
                probingHostId={probingHostId}
                setEnvironmentName={setEnvironmentName}
                setHostName={setHostName}
                setHostUrl={setHostUrl}
                setPrivateIp={setPrivateIp}
                setPublicIp={setPublicIp}
                setK8sCredentialContent={setK8sCredentialContent}
                setNamespaceKeysText={setNamespaceKeysText}
              />
            ) : activeNav === "中间件资源信息" ? (
              <MiddlewareResourceManager accessToken={session.access_token} />
            ) : (
              <RbacOverview
                menus={menus}
                metrics={metrics}
                permissions={permissions}
                roles={roles}
                users={users}
              />
            )}
          </div>
        </section>
      </div>
    </main>
  );
}

const middlewareViews = ["中间件实例", "账号资产", "权限范围"] as const;

function MiddlewareResourceManager({ accessToken }: { accessToken: string }) {
  const [activeView, setActiveView] = useState<(typeof middlewareViews)[number]>("中间件实例");
  const [instances, setInstances] = useState<MiddlewareInstance[]>([]);
  const [environmentName, setEnvironmentName] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const loadInstances = useCallback(async () => {
    const response = await fetch(`${apiBaseUrl}/api/middleware/instances?middleware_type=nacos`, {
      headers: { Authorization: `Bearer ${accessToken}` },
    });
    const data = await response.json().catch(() => []);
    if (!response.ok) {
      throw new Error(data.detail ?? "加载 Nacos 实例失败");
    }
    setInstances(data as MiddlewareInstance[]);
  }, [accessToken]);

  useEffect(() => {
    let cancelled = false;
    fetch(`${apiBaseUrl}/api/middleware/instances?middleware_type=nacos`, {
      headers: { Authorization: `Bearer ${accessToken}` },
    })
      .then(async (response) => {
        const data = await response.json().catch(() => []);
        if (!response.ok) {
          throw new Error(data.detail ?? "加载 Nacos 实例失败");
        }
        return data as MiddlewareInstance[];
      })
      .then((rows) => {
        if (!cancelled) {
          setInstances(rows);
        }
      })
      .catch((loadError) => {
        if (!cancelled) {
          setError(loadError instanceof Error ? loadError.message : "加载 Nacos 实例失败");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [accessToken]);

  async function handleCreateInstance(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError("");
    setNotice("");
    try {
      const response = await fetch(`${apiBaseUrl}/api/middleware/instances`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${accessToken}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          environment_name: environmentName,
          base_url: baseUrl,
          username,
          password,
        }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data.detail ?? "添加 Nacos 实例失败");
      }
      setEnvironmentName("");
      setBaseUrl("");
      setUsername("");
      setPassword("");
      await loadInstances();
      setNotice("Nacos 连接信息已加密保存。");
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "添加 Nacos 实例失败");
    } finally {
      setSaving(false);
    }
  }

  async function handleDeleteInstance(instanceId: number) {
    if (!window.confirm("确认删除这条 Nacos 连接信息吗？")) {
      return;
    }
    setError("");
    setNotice("");
    try {
      const response = await fetch(`${apiBaseUrl}/api/middleware/instances/${instanceId}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${accessToken}` },
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data.detail ?? "删除 Nacos 实例失败");
      }
      await loadInstances();
      setNotice("Nacos 连接信息已删除。");
    } catch (deleteError) {
      setError(deleteError instanceof Error ? deleteError.message : "删除 Nacos 实例失败");
    }
  }

  return (
    <section className="space-y-5">
      <div className="flex flex-wrap gap-2 border-b border-white/10 pb-4">
        {middlewareViews.map((view) => (
          <button
            className={`h-10 rounded-[6px] px-4 text-sm font-bold transition ${
              activeView === view
                ? "bg-[#0a1ae1] text-white"
                : "border border-[#1b255d] bg-[#070b1b] text-[#bfc9e7]/72 hover:border-[#4b5fc6] hover:text-white"
            }`}
            key={view}
            onClick={() => setActiveView(view)}
            type="button"
          >
            {view}
          </button>
        ))}
      </div>

      {activeView === "中间件实例" ? (
        <form
          className="grid gap-4 rounded-[8px] border border-white/10 bg-[#04050b]/52 p-5 shadow-2xl backdrop-blur md:grid-cols-2 xl:grid-cols-4"
          onSubmit={handleCreateInstance}
        >
          <label className="block">
            <span className="mb-2 block text-xs font-bold text-[#bfc9e7]/60">所属环境</span>
            <input
              className="h-11 w-full rounded-[6px] border border-[#1b255d] bg-[#070b1b] px-3 text-sm outline-none focus:border-[#7f91ff]"
              onChange={(event) => setEnvironmentName(event.target.value)}
              placeholder="例如开发环境 GPU"
              required
              value={environmentName}
            />
          </label>
          <label className="block">
            <span className="mb-2 block text-xs font-bold text-[#bfc9e7]/60">Nacos URL</span>
            <input
              className="h-11 w-full rounded-[6px] border border-[#1b255d] bg-[#070b1b] px-3 text-sm outline-none focus:border-[#7f91ff]"
              onChange={(event) => setBaseUrl(event.target.value)}
              placeholder="http://nacos.example.internal:8848/nacos"
              required
              type="url"
              value={baseUrl}
            />
          </label>
          <label className="block">
            <span className="mb-2 block text-xs font-bold text-[#bfc9e7]/60">用户名</span>
            <input
              autoComplete="off"
              className="h-11 w-full rounded-[6px] border border-[#1b255d] bg-[#070b1b] px-3 text-sm outline-none focus:border-[#7f91ff]"
              onChange={(event) => setUsername(event.target.value)}
              required
              value={username}
            />
          </label>
          <label className="block">
            <span className="mb-2 block text-xs font-bold text-[#bfc9e7]/60">密码</span>
            <input
              autoComplete="new-password"
              className="h-11 w-full rounded-[6px] border border-[#1b255d] bg-[#070b1b] px-3 text-sm outline-none focus:border-[#7f91ff]"
              onChange={(event) => setPassword(event.target.value)}
              required
              type="password"
              value={password}
            />
          </label>
          <button
            className="h-11 rounded-[6px] bg-[#0a1ae1] px-5 text-sm font-black text-white transition hover:bg-[#1628ff] disabled:cursor-not-allowed disabled:opacity-60 md:col-span-2 xl:col-span-4"
            disabled={saving}
            type="submit"
          >
            {saving ? "加密保存中..." : "添加 Nacos"}
          </button>
        </form>
      ) : null}

      {error ? (
        <p className="rounded-[6px] border border-[#ff4d5d]/40 bg-[#a30613]/18 px-4 py-3 text-sm text-[#ff9aa3]">{error}</p>
      ) : null}
      {notice ? (
        <p className="rounded-[6px] border border-[#4b5fc6]/60 bg-[#0a1ae1]/16 px-4 py-3 text-sm text-[#bfc9e7]">{notice}</p>
      ) : null}

      <article className="rounded-[8px] border border-white/10 bg-[#04050b]/52 p-5 shadow-2xl backdrop-blur">
        <div className="mb-5">
          <h2 className="text-lg font-black text-white">{activeView}</h2>
          <p className="mt-2 text-sm text-[#bfc9e7]/58">{middlewareViewDescription(activeView)}</p>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[1080px] border-collapse text-sm">
            <thead>
              <tr className="border-b border-white/10 text-left text-[#bfc9e7]/60">
                {middlewareViewColumns(activeView).map((column) => (
                  <th className="py-3 font-semibold" key={column}>{column}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {activeView === "中间件实例" && instances.length > 0 ? (
                instances.map((instance) => (
                  <tr className="border-b border-white/8" key={instance.id}>
                    <td className="py-4 font-bold text-white">{instance.environment_name}</td>
                    <td className="py-4 text-[#bfc9e7]/78">Nacos</td>
                    <td className="py-4 text-[#bfc9e7]/78">{instance.instance_name}</td>
                    <td className="max-w-[320px] truncate py-4 text-[#bfc9e7]/64">{instance.base_url}</td>
                    <td className="py-4 text-[#bfc9e7]/78">{instance.username}</td>
                    <td className="py-4">
                      <span className="rounded-full bg-[#0a1ae1]/30 px-3 py-1 text-xs font-bold text-[#9fb0ff]">
                        {middlewareStatusLabel(instance.status)}
                      </span>
                    </td>
                    <td className="py-4 text-[#bfc9e7]/78">{instance.credential_configured ? "已加密" : "未配置"}</td>
                    <td className="py-4 text-[#bfc9e7]/64">{formatHostTime(instance.created_at)}</td>
                    <td className="py-4 text-right">
                      <button className="text-sm font-bold text-[#ff7f8a]" onClick={() => handleDeleteInstance(instance.id)} type="button">删除</button>
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td className="py-16 text-center text-sm text-[#bfc9e7]/48" colSpan={middlewareViewColumns(activeView).length}>
                    {middlewareViewEmptyState(activeView)}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </article>
    </section>
  );
}

function middlewareViewDescription(view: (typeof middlewareViews)[number]): string {
  if (view === "账号资产") {
    return "汇总各环境中间件账号、负责人、凭据托管状态和账号生命周期。";
  }
  if (view === "权限范围") {
    return "展示账号在数据库、Topic、ACL、Key 空间等资源上的授权范围。";
  }
  return "统一登记 MySQL、Redis、Kafka、Doris、Nacos、Milvus 等中间件实例。";
}

function middlewareViewColumns(view: (typeof middlewareViews)[number]): string[] {
  if (view === "账号资产") {
    return ["环境", "中间件", "用户名", "负责人", "凭据状态", "账号状态", "最近同步"];
  }
  if (view === "权限范围") {
    return ["环境", "中间件", "账号", "资源范围", "权限", "来源", "更新时间"];
  }
  return ["环境", "类型", "实例名称", "连接地址", "用户名", "接入状态", "凭据", "添加时间", "操作"];
}

function middlewareViewEmptyState(view: (typeof middlewareViews)[number]): string {
  if (view === "账号资产") {
    return "暂无已同步的中间件账号";
  }
  if (view === "权限范围") {
    return "暂无已采集的权限信息";
  }
  return "暂无已接入的中间件实例";
}

function middlewareStatusLabel(status: MiddlewareInstance["status"]): string {
  if (status === "active") {
    return "活跃";
  }
  if (status === "unreachable") {
    return "无法连接";
  }
  if (status === "disabled") {
    return "已停用";
  }
  return "已配置";
}

function readBackendAdminSession(): { access_token: string; client_type: string } | null {
  try {
    const rawSession = window.localStorage.getItem(backendAdminSessionStorageKey);
    if (!rawSession) {
      return null;
    }
    const session = JSON.parse(rawSession) as { access_token?: string; client_type?: string };
    if (!session.access_token || session.client_type !== backendAdminClientType) {
      return null;
    }
    return { access_token: session.access_token, client_type: backendAdminClientType };
  } catch {
    return null;
  }
}

function RbacOverview({
  metrics,
  users,
  roles,
  permissions,
  menus,
}: {
  metrics: { label: string; value: number; hint: string }[];
  users: ApiUser[];
  roles: ApiRole[];
  permissions: ApiPermission[];
  menus: ApiMenu[];
}) {
  return (
    <>
      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {metrics.map((card) => (
          <article className="rounded-[8px] border border-white/10 bg-[#04050b]/48 p-5 shadow-2xl backdrop-blur" key={card.label}>
            <p className="text-sm text-[#bfc9e7]/62">{card.label}</p>
            <p className="mt-3 text-3xl font-black text-white">{card.value}</p>
            <p className="mt-2 text-xs text-[#4b5fc6]">{card.hint}</p>
          </article>
        ))}
      </section>

      <section className="grid gap-6 xl:grid-cols-[1.25fr_0.75fr]">
        <article className="rounded-[8px] border border-white/10 bg-[#04050b]/52 p-5 shadow-2xl backdrop-blur">
          <h2 className="mb-4 text-lg font-black">用户列表</h2>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[620px] border-collapse text-sm">
              <thead>
                <tr className="border-b border-white/10 text-left text-[#bfc9e7]/60">
                  <th className="py-3 font-semibold">账号</th>
                  <th className="py-3 font-semibold">名称</th>
                  <th className="py-3 font-semibold">状态</th>
                  <th className="py-3 font-semibold">最近登录</th>
                </tr>
              </thead>
              <tbody>
                {users.map((user) => (
                  <tr className="border-b border-white/8" key={user.id}>
                    <td className="py-4 font-bold text-white">{user.username}</td>
                    <td className="py-4 text-[#bfc9e7]/78">{user.displayName ?? user.display_name ?? "-"}</td>
                    <td className="py-4 text-[#bfc9e7]/70">{user.is_active === false ? "禁用" : "启用"}</td>
                    <td className="py-4 text-[#bfc9e7]/70">{user.last_login_at ?? "暂无记录"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </article>

        <article className="rounded-[8px] border border-white/10 bg-[#04050b]/52 p-5 shadow-2xl backdrop-blur">
          <h2 className="mb-4 text-lg font-black">角色权限</h2>
          <div className="space-y-3">
            {roles.map((role) => (
              <div className="rounded-[6px] border border-white/10 bg-[#070b1b] p-4" key={role.code}>
                <p className="font-bold text-white">{role.name ?? role.code}</p>
                <p className="mt-2 text-sm text-[#bfc9e7]/64">{role.description ?? role.code}</p>
              </div>
            ))}
          </div>
        </article>
      </section>

      <section className="grid gap-6 xl:grid-cols-2">
        <article className="rounded-[8px] border border-white/10 bg-[#04050b]/52 p-5 shadow-2xl backdrop-blur">
          <h2 className="mb-4 text-lg font-black">权限点</h2>
          <div className="flex flex-wrap gap-3">
            {permissions.map((permission) => (
              <span className="rounded-[5px] border border-[#1b255d] bg-[#070b1b] px-3 py-2 text-sm text-[#bfc9e7]" key={permission.code}>
                {permission.code}
              </span>
            ))}
          </div>
        </article>

        <article className="rounded-[8px] border border-white/10 bg-[#04050b]/52 p-5 shadow-2xl backdrop-blur">
          <h2 className="mb-4 text-lg font-black">菜单树</h2>
          <div className="space-y-3">
            {menus.map((menu) => (
              <div className="rounded-[6px] border border-white/10 bg-[#070b1b] p-4" key={menu.code}>
                <div className="flex items-center justify-between gap-3">
                  <p className="font-bold text-white">{menu.title}</p>
                  <span className="text-xs text-[#4b5fc6]">{menu.path}</span>
                </div>
                <p className="mt-2 text-sm leading-6 text-[#bfc9e7]/64">编码：{menu.code}</p>
              </div>
            ))}
          </div>
        </article>
      </section>
    </>
  );
}

function MachineHostManager({
  hosts,
  hostUrl,
  hostName,
  publicIp,
  privateIp,
  environmentName,
  namespaceKeysText,
  k8sCredentialContent,
  editingHostId,
  hostSaving,
  hostError,
  hostNotice,
  probingHostId,
  setHostUrl,
  setHostName,
  setPublicIp,
  setPrivateIp,
  setEnvironmentName,
  setNamespaceKeysText,
  setK8sCredentialContent,
  onSaveHost,
  onEditHost,
  onProbeHost,
  onCancelEdit,
  onDeleteHost,
}: {
  hosts: HostRecord[];
  hostUrl: string;
  hostName: string;
  publicIp: string;
  privateIp: string;
  environmentName: string;
  namespaceKeysText: string;
  k8sCredentialContent: string;
  editingHostId: number | null;
  hostSaving: boolean;
  hostError: string;
  hostNotice: HostNotice | null;
  probingHostId: number | null;
  setHostUrl: (value: string) => void;
  setHostName: (value: string) => void;
  setPublicIp: (value: string) => void;
  setPrivateIp: (value: string) => void;
  setEnvironmentName: (value: string) => void;
  setNamespaceKeysText: (value: string) => void;
  setK8sCredentialContent: (value: string) => void;
  onSaveHost: (event: FormEvent<HTMLFormElement>) => void;
  onEditHost: (host: HostRecord) => void;
  onProbeHost: (hostId: number) => void;
  onCancelEdit: () => void;
  onDeleteHost: (hostId: number) => void;
}) {
  return (
    <>
      <form className="grid gap-4 rounded-[8px] border border-white/10 bg-[#04050b]/52 p-5 shadow-2xl backdrop-blur md:grid-cols-2 xl:grid-cols-3" onSubmit={onSaveHost}>
        <label className="block">
          <span className="mb-2 block text-xs font-bold text-[#bfc9e7]/60">机器名字</span>
          <input className="h-11 w-full rounded-[6px] border border-[#1b255d] bg-[#070b1b] px-3 text-sm outline-none focus:border-[#7f91ff]" onChange={(event) => setHostName(event.target.value)} placeholder="例如 dev-gpu-node-01" required value={hostName} />
        </label>
        <label className="block">
          <span className="mb-2 block text-xs font-bold text-[#bfc9e7]/60">所属环境</span>
          <input className="h-11 w-full rounded-[6px] border border-[#1b255d] bg-[#070b1b] px-3 text-sm outline-none focus:border-[#7f91ff]" onChange={(event) => setEnvironmentName(event.target.value)} placeholder="例如 开发 GPU 环境" required value={environmentName} />
        </label>
        <label className="block">
          <span className="mb-2 block text-xs font-bold text-[#bfc9e7]/60">node-exporter URL</span>
          <input className="h-11 w-full rounded-[6px] border border-[#1b255d] bg-[#070b1b] px-3 text-sm outline-none focus:border-[#7f91ff]" onChange={(event) => setHostUrl(event.target.value)} placeholder="http://host:9100/metrics" required value={hostUrl} />
        </label>
        <label className="block">
          <span className="mb-2 block text-xs font-bold text-[#bfc9e7]/60">公网 IP</span>
          <input className="h-11 w-full rounded-[6px] border border-[#1b255d] bg-[#070b1b] px-3 text-sm outline-none focus:border-[#7f91ff]" onChange={(event) => setPublicIp(event.target.value)} placeholder="可从 URL 推断" value={publicIp} />
        </label>
        <label className="block">
          <span className="mb-2 block text-xs font-bold text-[#bfc9e7]/60">私网 IP</span>
          <input className="h-11 w-full rounded-[6px] border border-[#1b255d] bg-[#070b1b] px-3 text-sm outline-none focus:border-[#7f91ff]" onChange={(event) => setPrivateIp(event.target.value)} placeholder="手动填写" value={privateIp} />
        </label>
        <label className="block md:col-span-2 xl:col-span-3">
          <span className="mb-2 block text-xs font-bold text-[#bfc9e7]/60">Namespace Key 白名单</span>
          <input className="h-11 w-full rounded-[6px] border border-[#1b255d] bg-[#070b1b] px-3 font-mono text-sm outline-none focus:border-[#7f91ff]" onChange={(event) => setNamespaceKeysText(event.target.value)} placeholder="例如 dev, prod（逗号、空格或换行分隔）" value={namespaceKeysText} />
          <span className="mt-1 block text-xs text-[#bfc9e7]/52">用户端只能查询这些 Namespace 下 Pod 的环境变量名称；留空表示不开放该能力。</span>
        </label>
        <label className="block md:col-span-2 xl:col-span-3">
          <span className="mb-2 block text-xs font-bold text-[#bfc9e7]/60">K8S 凭证内容</span>
          <textarea className="min-h-52 w-full resize-y rounded-[6px] border border-[#1b255d] bg-[#070b1b] px-3 py-3 font-mono text-xs leading-5 outline-none focus:border-[#7f91ff]" onChange={(event) => setK8sCredentialContent(event.target.value)} placeholder="可选：在这里粘贴完整 kubeconfig YAML 内容" value={k8sCredentialContent} />
          {editingHostId ? <span className="mt-1 block text-xs text-[#bfc9e7]/52">留空会保留当前已加密保存的凭证；粘贴新内容会覆盖更新。</span> : null}
        </label>
        <div className="flex gap-3 md:col-span-2 xl:col-span-3">
          <button className="h-11 flex-1 rounded-[6px] bg-[#0a1ae1] px-5 text-sm font-black text-white transition hover:bg-[#1628ff] disabled:cursor-not-allowed disabled:opacity-60" disabled={hostSaving} type="submit">
            {hostSaving ? "检测并保存中..." : editingHostId ? "整体更新" : "整体提交"}
          </button>
          {editingHostId ? <button className="h-11 rounded-[6px] border border-[#4b5fc6] px-5 text-sm font-bold text-[#bfc9e7]" onClick={onCancelEdit} type="button">取消编辑</button> : null}
        </div>
      </form>

      {hostError ? (
        <p className="rounded-[6px] border border-[#ff4d5d]/40 bg-[#a30613]/18 px-4 py-3 text-sm text-[#ff9aa3]">{hostError}</p>
      ) : null}

      {hostNotice ? (
        <p
          className={`rounded-[6px] border px-4 py-3 text-sm ${
            hostNotice.tone === "success"
              ? "border-[#4b5fc6]/60 bg-[#0a1ae1]/16 text-[#bfc9e7]"
              : "border-[#f2b84b]/40 bg-[#6b4b08]/22 text-[#ffd889]"
          }`}
        >
          {hostNotice.message}
        </p>
      ) : null}

      <article className="rounded-[8px] border border-white/10 bg-[#04050b]/52 p-5 shadow-2xl backdrop-blur">
        <h2 className="mb-4 text-lg font-black">已添加的主机信息</h2>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[1380px] border-collapse text-sm">
            <thead>
              <tr className="border-b border-white/10 text-left text-[#bfc9e7]/60">
                <th className="py-3 font-semibold">主机名</th>
                <th className="py-3 font-semibold">所属环境</th>
                <th className="py-3 font-semibold">公网 IP</th>
                <th className="py-3 font-semibold">私网 IP</th>
                <th className="py-3 font-semibold">状态</th>
                <th className="py-3 font-semibold">连接说明</th>
                <th className="py-3 font-semibold">K8S 凭证</th>
                <th className="py-3 font-semibold">Namespace Key</th>
                <th className="py-3 font-semibold">node-exporter</th>
                <th className="py-3 text-right font-semibold">操作</th>
              </tr>
            </thead>
            <tbody>
              {hosts.map((host) => (
                <tr className="border-b border-white/8" key={host.id}>
                  <td className="py-4 font-bold text-white">{host.hostname || "未命名主机"}</td>
                  <td className="py-4 text-[#bfc9e7]/78">{host.environment_name || "未关联"}</td>
                  <td className="py-4 text-[#bfc9e7]/78">{host.public_ip || "-"}</td>
                  <td className="py-4 text-[#bfc9e7]/78">{host.private_ip || "未填写"}</td>
                  <td className="py-4">
                    <span className={`rounded-full px-3 py-1 text-xs font-bold ${host.status === "active" ? "bg-[#0a1ae1]/30 text-[#9fb0ff]" : "bg-[#a30613]/24 text-[#ff6b76]"}`}>
                      {host.status === "active" ? "活跃" : "无法连接"}
                    </span>
                  </td>
                  <td className="max-w-[340px] py-4 pr-5 text-xs leading-5">
                    <p className={host.status === "active" ? "text-[#9fb0ff]" : "text-[#ff9aa3]"}>
                      {host.status === "active" ? "node-exporter 连接正常" : host.last_error ?? "未返回详细原因"}
                    </p>
                    {host.last_seen_at ? (
                      <p className="mt-1 text-[#bfc9e7]/45">最近成功：{formatHostTime(host.last_seen_at)}</p>
                    ) : null}
                  </td>
                  <td className="py-4 text-[#bfc9e7]/78">{host.has_k8s_credential ? "已配置" : "未配置"}</td>
                  <td className="max-w-[260px] py-4 pr-5 font-mono text-xs text-[#bfc9e7]/70">
                    {host.namespace_keys?.length ? host.namespace_keys.join(", ") : "未开放"}
                  </td>
                  <td className="max-w-[280px] truncate py-4 text-[#bfc9e7]/64">{host.node_exporter_url}</td>
                  <td className="py-4 text-right">
                    <button
                      className="mr-4 text-sm font-bold text-[#7f91ff] disabled:cursor-not-allowed disabled:opacity-50"
                      disabled={probingHostId === host.id}
                      onClick={() => onProbeHost(host.id)}
                      type="button"
                    >
                      {probingHostId === host.id ? "检测中..." : "重新检测"}
                    </button>
                    <button className="mr-4 text-sm font-bold text-[#9fb0ff]" onClick={() => onEditHost(host)} type="button">编辑</button>
                    <button className="text-sm font-bold text-[#ff7f8a]" onClick={() => onDeleteHost(host.id)} type="button">
                      删除
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </article>

      <article className="rounded-[8px] border border-white/10 bg-[#04050b]/52 p-5 shadow-2xl backdrop-blur">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/10 pb-4">
          <div>
            <h2 className="text-lg font-black">NodePort 展示策略</h2>
            <p className="mt-1 text-xs text-[#bfc9e7]/52">普通用户端可见范围与常用端口注释</p>
          </div>
          <div className="flex gap-2 text-xs font-bold">
            <span className="rounded-full bg-[#0a1ae1]/24 px-3 py-1 text-[#9fb0ff]">默认放行</span>
            <span className="rounded-full border border-white/10 px-3 py-1 text-[#bfc9e7]/52">审计未启用</span>
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[820px] text-left text-sm">
            <thead className="text-xs text-[#bfc9e7]/52">
              <tr className="border-b border-white/10">
                <th className="py-3 pr-5">Namespace</th>
                <th className="py-3 pr-5">Service</th>
                <th className="py-3 pr-5">端口名称</th>
                <th className="py-3 pr-5">普通用户可见</th>
                <th className="py-3 pr-4">注释</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td className="py-8 text-center text-[#bfc9e7]/52" colSpan={5}>暂无自定义规则，当前展示全部 NodePort</td>
              </tr>
            </tbody>
          </table>
        </div>
      </article>
    </>
  );
}

function formatHostTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "medium",
    hour12: false,
  }).format(date);
}

function parseNamespaceKeys(value: string): string[] {
  return Array.from(
    new Set(
      value
        .split(/[\s,，]+/)
        .map((item) => item.trim())
        .filter(Boolean),
    ),
  );
}
