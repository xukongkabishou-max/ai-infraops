"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";

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

const apiBaseUrl =
  process.env.NEXT_PUBLIC_RBAC_API_BASE_URL ?? "http://localhost:8000";
const backendAdminSessionStorageKey = "ai-infraops:backend-admin-web-session";
const backendAdminClientType = "backend_admin_web";

const navItems = ["总览", "用户管理", "角色管理", "权限管理", "菜单管理", "机器资源信息"];

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
  const [k8sCredentialContent, setK8sCredentialContent] = useState("");
  const [editingHostId, setEditingHostId] = useState<number | null>(null);
  const [hostError, setHostError] = useState("");
  const [hostSaving, setHostSaving] = useState(false);

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
          k8s_credential_name: k8sCredentialContent ? `${hostName}.yaml` : "",
          k8s_credential_content: k8sCredentialContent,
        }),
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail ?? `${editingHostId ? "更新" : "添加"}主机失败`);
      }
      resetHostForm();
      await loadHosts();
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
    setK8sCredentialContent("");
  }

  function handleEditHost(host: HostRecord) {
    setEditingHostId(host.id);
    setHostUrl(host.node_exporter_url);
    setHostName(host.hostname);
    setPublicIp(host.public_ip);
    setPrivateIp(host.private_ip);
    setEnvironmentName(host.environment_name ?? "");
    setK8sCredentialContent("");
    setHostError("");
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  async function handleDeleteHost(hostId: number) {
    setHostError("");
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
                {activeNav === "机器资源信息" ? "添加、删除与检查环境主机" : "登录、用户、角色、权限、菜单"}
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
                hostName={hostName}
                hostSaving={hostSaving}
                hostUrl={hostUrl}
                hosts={hosts}
                privateIp={privateIp}
                publicIp={publicIp}
                k8sCredentialContent={k8sCredentialContent}
                onCancelEdit={resetHostForm}
                onEditHost={handleEditHost}
                onSaveHost={handleSaveHost}
                onDeleteHost={handleDeleteHost}
                setEnvironmentName={setEnvironmentName}
                setHostName={setHostName}
                setHostUrl={setHostUrl}
                setPrivateIp={setPrivateIp}
                setPublicIp={setPublicIp}
                setK8sCredentialContent={setK8sCredentialContent}
              />
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
  k8sCredentialContent,
  editingHostId,
  hostSaving,
  hostError,
  setHostUrl,
  setHostName,
  setPublicIp,
  setPrivateIp,
  setEnvironmentName,
  setK8sCredentialContent,
  onSaveHost,
  onEditHost,
  onCancelEdit,
  onDeleteHost,
}: {
  hosts: HostRecord[];
  hostUrl: string;
  hostName: string;
  publicIp: string;
  privateIp: string;
  environmentName: string;
  k8sCredentialContent: string;
  editingHostId: number | null;
  hostSaving: boolean;
  hostError: string;
  setHostUrl: (value: string) => void;
  setHostName: (value: string) => void;
  setPublicIp: (value: string) => void;
  setPrivateIp: (value: string) => void;
  setEnvironmentName: (value: string) => void;
  setK8sCredentialContent: (value: string) => void;
  onSaveHost: (event: FormEvent<HTMLFormElement>) => void;
  onEditHost: (host: HostRecord) => void;
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
          <span className="mb-2 block text-xs font-bold text-[#bfc9e7]/60">环境名称</span>
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

      <article className="rounded-[8px] border border-white/10 bg-[#04050b]/52 p-5 shadow-2xl backdrop-blur">
        <h2 className="mb-4 text-lg font-black">已添加的主机信息</h2>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[840px] border-collapse text-sm">
            <thead>
              <tr className="border-b border-white/10 text-left text-[#bfc9e7]/60">
                <th className="py-3 font-semibold">主机名</th>
                <th className="py-3 font-semibold">环境</th>
                <th className="py-3 font-semibold">公网 IP</th>
                <th className="py-3 font-semibold">私网 IP</th>
                <th className="py-3 font-semibold">状态</th>
                <th className="py-3 font-semibold">K8S 凭证</th>
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
                  <td className="py-4 text-[#bfc9e7]/78">{host.has_k8s_credential ? "已配置" : "未配置"}</td>
                  <td className="max-w-[280px] truncate py-4 text-[#bfc9e7]/64">{host.node_exporter_url}</td>
                  <td className="py-4 text-right">
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
    </>
  );
}
