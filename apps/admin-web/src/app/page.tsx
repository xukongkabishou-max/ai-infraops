"use client";

import { Fragment, FormEvent, useEffect, useMemo, useRef, useState } from "react";

type UserWebSession = {
  access_token: string;
  client_type: "user_web";
};

type UserWebAuthResponse = UserWebSession & {
  user: {
    isSuperuser: boolean;
  };
  roles: string[];
  permissions: string[];
  menus: Array<{
    code: string;
    path: string;
  }>;
};

type SectionKey = "machine" | "business" | "middleware" | "monitoring";
type MachinePageKey = "environmentApis" | "machineAccounts" | "middlewareAccounts";
type BusinessPageKey = "nodePorts" | "imageTags" | "gpuModels" | "envKeys";
type MiddlewarePageKey = "nacosKeys" | "healthChecks";

type ResourceHostOption = {
  host_id: number;
  environment_id: number;
  environment_name: string;
  hostname: string;
  public_ip?: string | null;
  private_ip?: string | null;
  resource_mode: "k8s_cluster" | "standalone";
  has_k8s_credential: boolean;
  status: "configured" | "active" | "unreachable" | "disabled";
  last_error?: string | null;
};

type ResourceCapacity = {
  totalBytes: number;
  usedBytes: number;
  availableBytes: number;
  usagePercent: number;
  totalHuman: string;
  usedHuman: string;
  availableHuman: string;
};

type ResourceNode = {
  name: string;
  ready: boolean;
  internal_ip?: string | null;
  external_ip?: string | null;
  metrics_available: boolean;
  metrics_error?: string | null;
  cpu: {
    coreCount: number;
    usagePercent: number;
    window: "5m" | "sample";
  };
  memory: ResourceCapacity;
  rootDisk: ResourceCapacity;
};

type ResourceInventory = {
  resource_mode: "k8s_cluster" | "standalone";
  host: ResourceHostOption;
  scraped_at: string;
  node_count: number;
  nodes: ResourceNode[];
};

type LinuxAccountHost = {
  host_id: number;
  environment_id?: number | null;
  environment_name?: string | null;
  hostname: string;
  status: "active" | "unreachable";
  last_seen_at?: string | null;
};

type LinuxAccount = {
  username: string;
  uid: number;
  gid: number;
  comment: string;
  home: string;
  shell: string;
  login_enabled: boolean;
};

type LinuxAccountInventory = {
  host: LinuxAccountHost;
  inventory: {
    hostname: string;
    collected_at: string;
    discovered_count: number;
    total_count: number;
    human_count: number;
    login_enabled_count: number;
    users: LinuxAccount[];
  };
};

type K8sHostOption = {
  host_id: number;
  environment_id: number;
  environment_name: string;
  hostname: string;
  public_ip?: string | null;
  cluster_id: number;
  status: "configured" | "active" | "unreachable" | "disabled";
  last_error?: string | null;
};

type ControllerImage = {
  controller_type: "Deployment" | "StatefulSet" | "DaemonSet";
  controller_name: string;
  pod_name: string;
  ready_replicas: number;
  desired_replicas: number;
  containers: Array<{ name: string; image: string }>;
};

type EnvK8sHostOption = K8sHostOption & {
  namespace_keys: string[];
};

type EnvWorkload = {
  kind: "Deployment" | "StatefulSet";
  name: string;
  ready_replicas: number;
  desired_replicas: number;
};

type EnvKeyResult = {
  namespace: string;
  workload: { kind: "Deployment" | "StatefulSet"; name: string };
  pod_name: string;
  containers: Array<{
    container_name: string;
    keys: string[];
    error?: string | null;
  }>;
};

type NodePortService = {
  service_name: string;
  service_display_name: string;
  port_name: string;
  protocol: string;
  service_port: number;
  node_port: number;
  public_address?: string | null;
  visible: boolean;
  note?: string | null;
};

const environmentKeysPageSize = 15;

type NacosInstanceOption = {
  id: number;
  environment_id: number;
  environment_name: string;
  instance_name: string;
  status: "configured" | "active" | "unreachable" | "disabled";
  last_seen_at?: string | null;
};

type NacosCatalog = {
  instance: NacosInstanceOption;
  namespace_count: number;
  config_count: number;
  namespaces: Array<{
    namespace_id: string;
    namespace_name: string;
    config_count: number;
    configs: Array<{
      group: string;
      data_id: string;
      type: string;
    }>;
  }>;
};

type NacosConfigStructure = {
  instance: NacosInstanceOption;
  namespace_id: string;
  group: string;
  data_id: string;
  format: "yaml" | "json";
  key_count: number;
  structure: string;
};

type MysqlDashboardOption = {
  id: number;
  environment_id: number;
  environment_name: string;
  instance_name: string;
  dashboard_url?: string | null;
  status: "configured" | "active" | "unreachable" | "disabled";
  last_seen_at?: string | null;
};

type DatabaseInstanceOption = {
  id: number;
  environment_id: number;
  environment_name: string;
  instance_name: string;
  status: "configured" | "active" | "unreachable" | "disabled";
  last_seen_at?: string | null;
};

type DatabaseAccount = {
  user_identity: string;
  username: string;
  host: string;
  comment: string;
  roles: string[];
  privileges: Array<{
    scope: string;
    value: string;
  }>;
  password_managed: boolean;
  password_updated_at?: string | null;
  password_last_action?: "verified" | "reset" | "manual" | null;
};

type DatabaseAccountInventory = {
  instance: DatabaseInstanceOption;
  account_count: number;
  accounts: DatabaseAccount[];
};

type DatabasePasswordCheck = {
  password: string;
  status: "idle" | "checking" | "matched" | "mismatch" | "resetting";
  message: string;
};

type DatabaseManagedPasswordState = {
  value: string;
  visible: boolean;
  editing: boolean;
  status: "idle" | "loading" | "loaded" | "error";
  message: string;
};

const navigationItems: Array<{
  key: SectionKey;
  label: string;
  hint: string;
  menuCode: string;
  permission: string;
}> = [
  { key: "machine", label: "机器信息管理", hint: "主机、日志、K8S 事件、账号", menuCode: "portal.machine", permission: "page:machine:view" },
  { key: "business", label: "业务系统管理", hint: "NodePort、镜像、模型、环境变量", menuCode: "portal.business", permission: "page:business:view" },
  { key: "middleware", label: "中间件系统管理", hint: "Nacos、数据库可用性", menuCode: "portal.middleware", permission: "page:middleware:view" },
  { key: "monitoring", label: "监控系统集成", hint: "待定能力预留", menuCode: "portal.monitoring", permission: "page:monitoring:view" },
];

const sectionMeta: Record<
  SectionKey,
  {
    eyebrow: string;
    title: string;
    summary: string;
    implementation: string;
  }
> = {
  machine: {
    eyebrow: "机器信息管理",
    title: "集群资源、机器账号与中间件账号",
    summary:
      "面向研发提供各环境主机资源和账号信息入口；K8S 环境按集群节点展示，独立主机按 node-exporter 展示。",
    implementation: "K8S 节点信息通过已登记 kubeconfig 访问 Prometheus Service Proxy；独立主机继续通过 node-exporter 获取。",
  },
  business: {
    eyebrow: "业务系统管理",
    title: "服务端口、镜像版本、GPU 模型与环境变量",
    summary:
      "展示各环境服务对外 NodePort、当前镜像 tag、GPU 环境模型部署状态、显存占用和空闲卡位，并列出服务环境变量 key。",
    implementation: "服务信息通过 K8S API 获取，GPU 信息通过 dcgm-exporter 获取；环境变量 key 通过受 Namespace 白名单约束的 K8S Pod Exec 获取。",
  },
  middleware: {
    eyebrow: "中间件系统管理",
    title: "配置目录与核心中间件可用性校验",
    summary:
      "展示 Nacos 的 Namespace、Group、配置名称与格式，并为 MySQL、Doris、Redis、Kafka 等核心组件预留快速可用性校验入口。",
    implementation: "Nacos 目录通过官方元数据接口获取；用户点选单个 YAML/JSON 配置后，正文仅在服务端内存中解析并清空 value。数据库可用性后续通过脚本模拟读写、生产消费和删除流程。",
  },
  monitoring: {
    eyebrow: "监控系统集成",
    title: "监控入口与告警聚合预留",
    summary: "为后续接入 Prometheus、Loki、告警中心、SLO 守护和统一可观测性视图预留页面骨架。",
    implementation: "当前先保留静态页面与接入清单，具体数据源和权限边界待定。",
  },
};

const telemetry = [
  { label: "GPU 集群", value: "97.8%", tone: "text-[#7dd3fc]" },
  { label: "待处理告警", value: "03", tone: "text-[#ff4b57]" },
  { label: "SLO 守护", value: "开启", tone: "text-[#9fb0ff]" },
];

const signals = [
  "K8s 集群配置已同步",
  "向量数据库延迟稳定",
  "Doris 数据链路运行正常",
];

const gpuModelRows = [
  { env: "开发 GPU 环境", model: "Qwen-72B-Instruct", gpu: "GPU-0, GPU-1", memory: "68 GiB / 96 GiB", freeCard: "GPU-2" },
  { env: "测试 GPU 环境", model: "Embedding-BGE", gpu: "GPU-3", memory: "18 GiB / 48 GiB", freeCard: "GPU-0, GPU-1" },
  { env: "生产 GPU 环境", model: "Rerank-Service", gpu: "GPU-5", memory: "9 GiB / 24 GiB", freeCard: "待接入" },
];

const healthCheckRows = [
  { middleware: "MySQL", check: "创建测试库表，执行 insert/select/update/delete 后清理", status: "脚本预留" },
  { middleware: "Doris", check: "写入临时表并执行聚合查询，验证 FE/BE 查询链路", status: "脚本预留" },
  { middleware: "Redis", check: "写入临时 key，读取校验 TTL，删除临时 key", status: "脚本预留" },
  { middleware: "Kafka", check: "生产测试消息并由临时 consumer group 消费确认", status: "脚本预留" },
];

const monitoringCards = [
  { title: "Prometheus 指标入口", detail: "统一登记 Prometheus 数据源、抓取任务和关键指标查询模板。" },
  { title: "Loki 日志入口", detail: "按环境、命名空间、服务名和 Trace ID 拼接日志查询地址。" },
  { title: "告警中心", detail: "后续聚合未恢复告警、告警责任人、静默窗口和处理记录。" },
  { title: "SLO 守护", detail: "预留核心业务 SLO、错误预算和服务可用性趋势展示。" },
];

const apiBaseUrl =
  process.env.NEXT_PUBLIC_ADMIN_API_BASE_URL ??
  process.env.NEXT_PUBLIC_RBAC_API_BASE_URL ??
  "http://localhost:8000";
const userSessionStorageKey = "ai-infraops:user-web-session";
const userWebClientType = "user_web";

export default function Home() {
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("admin");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [activeSection, setActiveSection] = useState<SectionKey>("machine");
  const [activeMachinePage, setActiveMachinePage] = useState<MachinePageKey>("environmentApis");
  const [activeBusinessPage, setActiveBusinessPage] = useState<BusinessPageKey>("nodePorts");
  const [activeMiddlewarePage, setActiveMiddlewarePage] = useState<MiddlewarePageKey>("nacosKeys");
  const [authenticated, setAuthenticated] = useState(false);
  const [isSuperuser, setIsSuperuser] = useState(false);
  const [permissions, setPermissions] = useState<string[]>([]);
  const [menus, setMenus] = useState<UserWebAuthResponse["menus"]>([]);

  const visibleNavigationItems = useMemo(() => {
    if (isSuperuser) return navigationItems;
    const permissionSet = new Set(permissions);
    const menuCodeSet = new Set(menus.map((menu) => menu.code));
    return navigationItems.filter(
      (item) => permissionSet.has(item.permission) && menuCodeSet.has(item.menuCode),
    );
  }, [isSuperuser, menus, permissions]);

  function applyAuthorization(data: UserWebAuthResponse) {
    setIsSuperuser(Boolean(data.user?.isSuperuser));
    setPermissions(data.permissions ?? []);
    setMenus(data.menus ?? []);
  }

  useEffect(() => {
    let alive = true;
    const savedSession = readUserWebSession();
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
        return response.json();
      })
      .then((data: UserWebAuthResponse) => {
        if (alive) {
          setAuthenticated(true);
          applyAuthorization(data);
        }
      })
      .catch(() => {
        window.localStorage.removeItem(userSessionStorageKey);
        if (alive) {
          setAuthenticated(false);
          setIsSuperuser(false);
          setPermissions([]);
          setMenus([]);
        }
      });

    return () => {
      alive = false;
    };
  }, []);

  async function handleLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError("");

    try {
      const response = await fetch(`${apiBaseUrl}/api/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password, client_type: userWebClientType }),
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail ?? "登录失败，请检查账号或密码");
      }
      const loginSession = data as UserWebAuthResponse;
      window.localStorage.setItem(
        userSessionStorageKey,
        JSON.stringify({
          access_token: loginSession.access_token,
          client_type: userWebClientType,
        }),
      );
      setAuthenticated(true);
      applyAuthorization(loginSession);
    } catch (loginError) {
      setError(loginError instanceof Error ? loginError.message : "登录失败");
    } finally {
      setLoading(false);
    }
  }

  function handleLogout() {
    const savedSession = readUserWebSession();
    if (savedSession) {
      fetch(`${apiBaseUrl}/api/auth/logout`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(savedSession),
      }).catch(() => undefined);
    }
    window.localStorage.removeItem(userSessionStorageKey);
    setAuthenticated(false);
    setIsSuperuser(false);
    setPermissions([]);
    setMenus([]);
  }

  if (authenticated) {
    const effectiveSection = visibleNavigationItems.some((item) => item.key === activeSection)
      ? activeSection
      : visibleNavigationItems[0]?.key;

    if (!effectiveSection) {
      return (
        <main className="grid min-h-screen place-items-center bg-[#04050b] px-6 text-white">
          <div className="max-w-lg border border-[#1b255d] bg-[#070b1b] p-8 text-center">
            <h1 className="text-xl font-black">当前账号没有可访问的页面</h1>
            <button className="mt-6 h-10 rounded-[6px] border border-[#4b5fc6] px-4 text-sm font-bold" onClick={handleLogout} type="button">
              退出登录
            </button>
          </div>
        </main>
      );
    }

    const meta = sectionMeta[effectiveSection];

    return (
      <main className="min-h-screen bg-[#04050b] text-white">
        <div className="grid min-h-screen lg:grid-cols-[272px_1fr]">
          <aside className="border-r border-[#1b255d] bg-[#070b1b] px-5 py-6">
            <div className="mb-8 flex items-center gap-3">
              <div className="grid h-11 w-11 place-items-center rounded-[6px] bg-[#0a1ae1] font-black shadow-[0_0_38px_rgba(10,26,225,0.55)]">
                AI
              </div>
              <div>
                <p className="text-sm text-[#bfc9e7]/80">InfraOps</p>
                <p className="text-xs text-[#4b5fc6]">统一运维控制中心</p>
              </div>
            </div>

            <nav className="space-y-2">
              {visibleNavigationItems.map((item) => {
                const active = item.key === effectiveSection;
                return (
                  <button
                    className={`w-full rounded-[6px] px-4 py-3 text-left transition ${
                      active
                        ? "bg-[#0a1ae1] text-white shadow-[0_12px_30px_rgba(10,26,225,0.28)]"
                        : "text-[#bfc9e7]/72 hover:bg-[#11183c] hover:text-white"
                    }`}
                    key={item.key}
                    onClick={() => setActiveSection(item.key)}
                    type="button"
                  >
                    <span className="block text-sm font-bold">{item.label}</span>
                    <span className={`mt-1 block text-xs ${active ? "text-white/70" : "text-[#bfc9e7]/48"}`}>
                      {item.hint}
                    </span>
                  </button>
                );
              })}
            </nav>
          </aside>

          <section className="min-w-0 bg-[radial-gradient(circle_at_75%_5%,rgba(10,26,225,0.30),transparent_30%),linear-gradient(135deg,#04050b_0%,#050e58_100%)]">
            <header className="flex flex-wrap items-center justify-between gap-4 border-b border-white/10 px-6 py-5 lg:px-8">
              <div className="max-w-5xl">
                <p className="text-sm font-semibold text-[#4b5fc6]">{meta.eyebrow}</p>
                <h1 className="mt-1 text-2xl font-black tracking-normal">{meta.title}</h1>
                <p className="mt-3 max-w-4xl text-sm leading-6 text-[#bfc9e7]/72">{meta.summary}</p>
              </div>
              <button
                className="h-10 rounded-[6px] border border-[#4b5fc6] px-4 text-sm font-bold text-[#bfc9e7] transition hover:bg-[#11183c]"
                onClick={handleLogout}
                type="button"
              >
                退出登录
              </button>
            </header>

            <div className="space-y-5 px-6 py-6 lg:px-8">
              <ImplementationPanel text={meta.implementation} />
              {effectiveSection === "machine" ? (
                <MachineInformationView
                  activePage={activeMachinePage}
                  isSuperuser={isSuperuser}
                  onSetActivePage={setActiveMachinePage}
                />
              ) : null}
              {effectiveSection === "business" ? (
                <BusinessSystemView activePage={activeBusinessPage} onSetActivePage={setActiveBusinessPage} />
              ) : null}
              {effectiveSection === "middleware" ? (
                <MiddlewareSystemView activePage={activeMiddlewarePage} onSetActivePage={setActiveMiddlewarePage} />
              ) : null}
              {effectiveSection === "monitoring" ? <MonitoringIntegrationView /> : null}
            </div>
          </section>
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen overflow-hidden bg-[#04050b] text-white">
      <section className="grid min-h-screen lg:grid-cols-[0.9fr_1.1fr]">
        <div className="relative flex min-h-screen items-center px-6 py-10 sm:px-10 lg:px-16">
          <div className="absolute inset-y-8 left-8 w-px bg-gradient-to-b from-transparent via-[#263075] to-transparent opacity-70" />
          <div className="absolute left-0 top-0 h-72 w-72 bg-[#0712a3]/25 blur-3xl" />

          <div className="relative z-10 mx-auto w-full max-w-[430px]">
            <div className="mb-14 flex items-center gap-3">
              <div className="grid h-11 w-11 place-items-center rounded-[6px] bg-[#0a1ae1] shadow-[0_0_45px_rgba(10,26,225,0.55)]">
                <span className="text-lg font-black tracking-tight">AI</span>
              </div>
              <div>
                <p className="text-sm text-[#bfc9e7]/70">InfraOps</p>
                <p className="text-sm text-[#4b5fc6]">统一运维控制中心</p>
              </div>
            </div>

            <p className="mb-4 text-sm font-semibold text-[#4b5fc6]">欢迎回来</p>
            <h1 className="max-w-sm text-5xl font-black leading-[0.96] tracking-normal text-white sm:text-6xl">
              一个入口，掌控全栈运维。
            </h1>
            <p className="mt-6 max-w-md text-base leading-7 text-[#bfc9e7]/72">
              登录 AI 基础设施运维驾驶舱，集中管理集群、告警、数据链路、权限与可观测性。
            </p>

            <form className="mt-10 space-y-5" onSubmit={handleLogin}>
              <label className="block">
                <span className="mb-2 block text-xs font-semibold text-[#bfc9e7]/60">工作账号</span>
                <input
                  className="h-14 w-full rounded-[4px] border border-[#1b255d] bg-[#070b1b] px-4 text-base text-white outline-none transition focus:border-[#4b5fc6] focus:shadow-[0_0_0_4px_rgba(75,95,198,0.18)]"
                  onChange={(event) => setUsername(event.target.value)}
                  placeholder="请输入工作账号"
                  type="text"
                  value={username}
                />
              </label>

              <label className="block">
                <span className="mb-2 block text-xs font-semibold text-[#bfc9e7]/60">登录密码</span>
                <input
                  className="h-14 w-full rounded-[4px] border border-[#1b255d] bg-[#070b1b] px-4 text-base text-white outline-none transition focus:border-[#4b5fc6] focus:shadow-[0_0_0_4px_rgba(75,95,198,0.18)]"
                  onChange={(event) => setPassword(event.target.value)}
                  placeholder="请输入安全密码"
                  type="password"
                  value={password}
                />
              </label>

              {error ? (
                <p className="rounded-[4px] border border-[#ff4b57]/40 bg-[#a30613]/18 px-4 py-3 text-sm text-[#ff9aa3]">
                  {error}
                </p>
              ) : null}

              <button
                className="group relative h-14 w-full overflow-hidden rounded-[4px] bg-[#0a1ae1] text-sm font-black text-white shadow-[0_18px_48px_rgba(10,26,225,0.36)] transition hover:bg-[#1628ff] disabled:cursor-not-allowed disabled:opacity-60"
                disabled={loading}
                type="submit"
              >
                <span className="absolute inset-y-0 -left-1/3 w-1/3 skew-x-[-18deg] bg-white/22 transition duration-500 group-hover:left-[120%]" />
                <span className="relative">{loading ? "正在校验..." : "进入控制台"}</span>
              </button>
            </form>
          </div>
        </div>

        <div className="relative hidden min-h-screen overflow-hidden bg-[#0712a3] lg:block">
          <div className="absolute inset-0 bg-[radial-gradient(circle_at_30%_20%,rgba(191,201,231,0.3),transparent_28%),linear-gradient(135deg,#0a1ae1_0%,#0712a3_48%,#050e58_100%)]" />
          <div className="absolute inset-0 opacity-25 [background-image:linear-gradient(rgba(255,255,255,0.09)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.09)_1px,transparent_1px)] [background-size:42px_42px]" />

          <div className="absolute right-[8%] top-[9%] flex gap-4">
            {telemetry.map((item) => (
              <div className="w-36 rounded-[6px] border border-white/14 bg-[#04050b]/38 p-4 shadow-2xl backdrop-blur" key={item.label}>
                <p className="text-[11px] text-[#bfc9e7]/60">{item.label}</p>
                <p className={`mt-2 text-2xl font-black ${item.tone}`}>{item.value}</p>
              </div>
            ))}
          </div>

          <div className="absolute left-[16%] top-[24%] h-[520px] w-[520px]">
            <div className="absolute left-24 top-8 h-80 w-80 rounded-full border border-[#bfc9e7]/16" />
            <div className="absolute left-10 top-20 h-96 w-96 rounded-full border border-[#4b5fc6]/34" />
            <div className="absolute left-0 top-40 h-72 w-[440px] rotate-[-12deg] rounded-full bg-[#04050b]/18 blur-md" />
            <div className="absolute left-40 top-28 h-48 w-44 rounded-t-[90px] bg-gradient-to-b from-[#bfc9e7] to-[#4b5fc6] shadow-[0_34px_80px_rgba(4,5,11,0.38)]" />
            <div className="absolute left-48 top-40 h-16 w-28 rounded-[8px] bg-[#04050b]" />
            <div className="absolute left-56 top-48 h-3 w-12 rounded-full bg-[#0a1ae1]" />
            <div className="absolute left-56 top-[264px] h-20 w-20 rounded-full border-[10px] border-[#04050b] bg-[#a30613] shadow-[0_0_30px_rgba(163,6,19,0.5)]" />
            <div className="absolute left-20 top-72 h-16 w-64 rounded-[10px] bg-[#04050b]/72 p-4 shadow-[0_24px_60px_rgba(4,5,11,0.45)]">
              <div className="mb-3 flex gap-2">
                <span className="h-2 w-2 rounded-full bg-[#a30613]" />
                <span className="h-2 w-2 rounded-full bg-[#4b5fc6]" />
                <span className="h-2 w-2 rounded-full bg-[#bfc9e7]" />
              </div>
              <div className="space-y-2">
                <span className="block h-2 w-44 rounded-full bg-[#4b5fc6]" />
                <span className="block h-2 w-32 rounded-full bg-[#bfc9e7]/70" />
              </div>
            </div>
            <div className="absolute left-80 top-80 h-28 w-28 rounded-full border-[14px] border-[#bfc9e7] bg-[#0a1ae1] shadow-[0_0_80px_rgba(191,201,231,0.5)]" />
            <span className="absolute left-[332px] top-[340px] h-3 w-3 rounded-full bg-white" />
            <span className="absolute left-[372px] top-[365px] h-3 w-3 rounded-full bg-white" />
            <span className="absolute left-[350px] top-[395px] h-3 w-3 rounded-full bg-white" />
          </div>

          <div className="absolute bottom-12 left-14 w-[420px] rounded-[8px] border border-white/14 bg-[#04050b]/44 p-5 shadow-2xl backdrop-blur">
            <p className="mb-4 text-xs font-bold text-[#bfc9e7]/62">实时就绪状态</p>
            <div className="space-y-3">
              {signals.map((signal, index) => (
                <div className="flex items-center gap-3" key={signal}>
                  <span className="grid h-6 w-6 place-items-center rounded-full bg-[#0a1ae1] text-[11px] font-black">
                    {index + 1}
                  </span>
                  <span className="text-sm text-white/86">{signal}</span>
                </div>
              ))}
            </div>
          </div>

          <div className="absolute -bottom-20 -right-24 h-72 w-72 rounded-full bg-[#a30613]/38 blur-3xl" />
        </div>
      </section>
    </main>
  );
}

function MachineInformationView({
  activePage,
  isSuperuser,
  onSetActivePage,
}: {
  activePage: MachinePageKey;
  isSuperuser: boolean;
  onSetActivePage: (page: MachinePageKey) => void;
}) {
  const pages: Array<{ key: MachinePageKey; label: string; hint: string }> = [
    { key: "environmentApis", label: "集群与主机资源", hint: "CPU、内存与根目录使用情况" },
    { key: "machineAccounts", label: "机器账号列表", hint: "各环境 Linux 机器账号" },
    { key: "middlewareAccounts", label: "中间件账号获取", hint: "按环境查询 Doris / MySQL 账号" },
  ];

  return (
    <div className="space-y-5">
      <SubPageNav activeKey={activePage} items={pages} onChange={onSetActivePage} />

      {activePage === "environmentApis" ? (
        <ResourceInventoryView />
      ) : null}

      {activePage === "machineAccounts" ? (
        <LinuxAccountInventoryView />
      ) : null}

      {activePage === "middlewareAccounts" ? (
        <DatabaseAccountInventoryView isSuperuser={isSuperuser} />
      ) : null}
    </div>
  );
}

function LinuxAccountInventoryView() {
  const [hosts, setHosts] = useState<LinuxAccountHost[]>([]);
  const [environment, setEnvironment] = useState("all");
  const [hostId, setHostId] = useState("");
  const [result, setResult] = useState<LinuxAccountInventory | null>(null);
  const [loadingHosts, setLoadingHosts] = useState(true);
  const [loadingAccounts, setLoadingAccounts] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    fetchUserApi<LinuxAccountHost[]>("/api/linux-accounts/hosts", controller.signal)
      .then((items) => {
        setHosts(items);
        setHostId(items[0] ? String(items[0].host_id) : "");
      })
      .catch((loadError) => {
        if (!controller.signal.aborted) {
          setError(loadError instanceof Error ? loadError.message : "加载主机失败");
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoadingHosts(false);
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!hostId) {
      setResult(null);
      return;
    }
    const controller = new AbortController();
    setLoadingAccounts(true);
    setError("");
    fetchUserApi<LinuxAccountInventory>(`/api/linux-accounts/hosts/${hostId}`, controller.signal)
      .then((data) => setResult(data))
      .catch((loadError) => {
        if (!controller.signal.aborted) {
          setResult(null);
          setError(loadError instanceof Error ? loadError.message : "获取账号列表失败");
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoadingAccounts(false);
      });
    return () => controller.abort();
  }, [hostId]);

  const environments = Array.from(
    new Set(hosts.map((host) => host.environment_name || "未关联环境")),
  );
  const visibleHosts = hosts.filter(
    (host) => environment === "all" || (host.environment_name || "未关联环境") === environment,
  );

  function handleEnvironmentChange(value: string) {
    setEnvironment(value);
    const nextHost = hosts.find(
      (host) => value === "all" || (host.environment_name || "未关联环境") === value,
    );
    setHostId(nextHost ? String(nextHost.host_id) : "");
  }

  async function refreshAccounts() {
    if (!hostId) return;
    setLoadingAccounts(true);
    setError("");
    try {
      setResult(await fetchUserApi<LinuxAccountInventory>(`/api/linux-accounts/hosts/${hostId}`));
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "获取账号列表失败");
    } finally {
      setLoadingAccounts(false);
    }
  }

  return (
    <SectionBlock title="各环境机器账号列表" description="只展示普通用户 UID 范围内的人工账号；root、系统账号和软件服务账号均已自动排除，不读取密码或密码哈希。">
      <div className="grid gap-4 rounded-[6px] border border-white/10 bg-[#070b1b] p-4 md:grid-cols-[1fr_1fr_auto]">
        <label className="block">
          <span className="mb-2 block text-xs font-semibold text-[#bfc9e7]/58">所属环境</span>
          <select className="h-11 w-full rounded-[6px] border border-[#1b255d] bg-[#04050b] px-3 text-sm outline-none focus:border-[#7f91ff]" onChange={(event) => handleEnvironmentChange(event.target.value)} value={environment}>
            <option value="all">全部环境</option>
            {environments.map((item) => <option key={item} value={item}>{item}</option>)}
          </select>
        </label>
        <label className="block">
          <span className="mb-2 block text-xs font-semibold text-[#bfc9e7]/58">主机</span>
          <select className="h-11 w-full rounded-[6px] border border-[#1b255d] bg-[#04050b] px-3 text-sm outline-none focus:border-[#7f91ff]" disabled={visibleHosts.length === 0} onChange={(event) => setHostId(event.target.value)} value={hostId}>
            {visibleHosts.length === 0 ? <option value="">暂无已接入主机</option> : null}
            {visibleHosts.map((host) => <option key={host.host_id} value={host.host_id}>{host.hostname}</option>)}
          </select>
        </label>
        <button className="h-11 self-end rounded-[6px] bg-[#0a1ae1] px-5 text-sm font-black transition hover:bg-[#1628ff] disabled:cursor-not-allowed disabled:opacity-60" disabled={!hostId || loadingAccounts} onClick={refreshAccounts} type="button">
          {loadingAccounts ? "获取中..." : "刷新账号列表"}
        </button>
      </div>

      {error ? <p className="mt-4 rounded-[6px] border border-[#ff4d5d]/40 bg-[#a30613]/18 px-4 py-3 text-sm text-[#ff9aa3]">{error}</p> : null}
      {loadingHosts ? <p className="mt-4 py-10 text-center text-sm text-[#bfc9e7]/58">正在加载已接入主机...</p> : null}
      {!loadingHosts && hosts.length === 0 ? <p className="mt-4 rounded-[6px] border border-dashed border-white/14 px-4 py-10 text-center text-sm text-[#bfc9e7]/58">后台尚未为任何主机配置用户管理 Agent 地址。</p> : null}

      {result ? (
        <div className="mt-5">
          <div className="mb-4 grid gap-3 sm:grid-cols-2">
            {[
              ["人工账号", result.inventory.total_count],
              ["可登录 Shell", result.inventory.login_enabled_count],
            ].map(([label, value]) => (
              <div className="rounded-[6px] border border-white/10 bg-[#070b1b] px-4 py-3" key={label}>
                <p className="text-xs text-[#bfc9e7]/52">{label}</p>
                <p className="mt-1 text-2xl font-black text-white">{value}</p>
              </div>
            ))}
          </div>
          <div className="mb-3 flex flex-wrap justify-between gap-2 text-xs text-[#bfc9e7]/52">
            <span>主机：{result.host.hostname}</span>
            <span>发现 {result.inventory.discovered_count} 个本地账号，排除 {result.inventory.discovered_count - result.inventory.total_count} 个系统基础账号</span>
            <span>采集时间：{formatDateTime(result.inventory.collected_at)}</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[920px] text-left text-sm">
              <thead><tr className="border-b border-white/10 text-xs text-[#bfc9e7]/52"><th className="py-3 pr-4">用户名</th><th className="py-3 pr-4">UID / GID</th><th className="py-3 pr-4">登录状态</th><th className="py-3 pr-4">Shell</th><th className="py-3 pr-4">Home</th><th className="py-3">备注</th></tr></thead>
              <tbody>
                {result.inventory.users.map((user) => (
                  <tr className="border-b border-white/8 text-[#bfc9e7]/78" key={`${user.username}-${user.uid}`}>
                    <td className="py-3 pr-4 font-bold text-white">{user.username}</td><td className="py-3 pr-4 font-mono text-xs">{user.uid} / {user.gid}</td><td className="py-3 pr-4">{user.login_enabled ? "可登录" : "已禁用 Shell"}</td><td className="py-3 pr-4 font-mono text-xs">{user.shell}</td><td className="py-3 pr-4 font-mono text-xs">{user.home}</td><td className="py-3">{user.comment || "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}
    </SectionBlock>
  );
}

function ResourceInventoryView() {
  const [targets, setTargets] = useState<ResourceHostOption[]>([]);
  const [environmentFilter, setEnvironmentFilter] = useState("all");
  const [inventories, setInventories] = useState<Record<number, ResourceInventory>>({});
  const [loadingByHost, setLoadingByHost] = useState<Record<number, boolean>>({});
  const [errorsByHost, setErrorsByHost] = useState<Record<number, string>>({});
  const [loadingTargets, setLoadingTargets] = useState(true);
  const [refreshingAll, setRefreshingAll] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    async function loadInitialResources() {
      try {
        const items = await fetchUserApi<ResourceHostOption[]>(
          "/api/resources/hosts",
          controller.signal,
        );
        if (controller.signal.aborted) return;

        setTargets(items);
        setLoadingTargets(false);
        setLoadingByHost(
          Object.fromEntries(items.map((item) => [item.host_id, true])),
        );

        await Promise.all(
          items.map(async (item) => {
            try {
              const detail = await fetchUserApi<ResourceInventory>(
                `/api/resources/hosts/${item.host_id}/metrics`,
                controller.signal,
              );
              if (controller.signal.aborted) return;
              setInventories((current) => ({ ...current, [item.host_id]: detail }));
              setErrorsByHost((current) => ({ ...current, [item.host_id]: "" }));
            } catch (loadError) {
              if (controller.signal.aborted) return;
              setErrorsByHost((current) => ({
                ...current,
                [item.host_id]: loadError instanceof Error ? loadError.message : "机器资源加载失败",
              }));
            } finally {
              if (!controller.signal.aborted) {
                setLoadingByHost((current) => ({ ...current, [item.host_id]: false }));
              }
            }
          }),
        );
      } catch (loadError) {
        if (loadError instanceof DOMException && loadError.name === "AbortError") {
          return;
        }
        setErrorsByHost({
          0: loadError instanceof Error ? loadError.message : "主机列表加载失败",
        });
      } finally {
        if (!controller.signal.aborted) {
          setLoadingTargets(false);
        }
      }
    }
    void loadInitialResources();
    return () => controller.abort();
  }, []);

  async function refreshHost(hostId: number) {
    setLoadingByHost((current) => ({ ...current, [hostId]: true }));
    setErrorsByHost((current) => ({ ...current, [hostId]: "" }));
    try {
      const detail = await fetchUserApi<ResourceInventory>(
        `/api/resources/hosts/${hostId}/metrics`,
      );
      setInventories((current) => ({ ...current, [hostId]: detail }));
    } catch (loadError) {
      setErrorsByHost((current) => ({
        ...current,
        [hostId]: loadError instanceof Error ? loadError.message : "机器资源加载失败",
      }));
    } finally {
      setLoadingByHost((current) => ({ ...current, [hostId]: false }));
    }
  }

  async function refreshAllHosts() {
    if (targets.length === 0) return;
    setRefreshingAll(true);
    try {
      await Promise.all(targets.map((target) => refreshHost(target.host_id)));
    } finally {
      setRefreshingAll(false);
    }
  }

  const environmentOptions = useMemo(
    () => Array.from(new Set(targets.map((target) => target.environment_name || "未关联环境"))),
    [targets],
  );
  const visibleTargets = useMemo(
    () => environmentFilter === "all"
      ? targets
      : targets.filter((target) => (target.environment_name || "未关联环境") === environmentFilter),
    [environmentFilter, targets],
  );

  return (
    <SectionBlock
      title="主机资源信息"
      description="全部主机统一展示；配置 K8S 凭证的环境展开集群内所有节点，未配置凭证的环境展示独立主机指标。"
    >
      <div className="mb-4 flex flex-wrap items-end justify-between gap-4">
        <label className="block w-full sm:w-[320px]">
          <span className="mb-2 block text-xs font-bold text-[#bfc9e7]/56">环境筛选</span>
          <select
            className="h-10 w-full rounded-[6px] border border-[#1b255d] bg-[#04050b] px-3 text-sm text-white outline-none transition focus:border-[#4b5fc6] disabled:cursor-not-allowed disabled:opacity-60"
            disabled={loadingTargets || targets.length === 0}
            onChange={(event) => setEnvironmentFilter(event.target.value)}
            value={environmentFilter}
          >
            <option value="all">全部环境（{environmentOptions.length}）</option>
            {environmentOptions.map((environmentName) => (
              <option key={environmentName} value={environmentName}>
                {environmentName}
              </option>
            ))}
          </select>
        </label>
        <button
          className="h-10 rounded-[6px] bg-[#0a1ae1] px-5 text-sm font-black text-white transition hover:bg-[#1628ff] disabled:cursor-not-allowed disabled:opacity-60"
          disabled={loadingTargets || refreshingAll || targets.length === 0}
          onClick={refreshAllHosts}
          type="button"
        >
          {refreshingAll ? "正在全部刷新..." : "全部刷新指标"}
        </button>
      </div>

      <div className="overflow-x-auto rounded-[6px] border border-white/10">
        <table className="w-full min-w-[1160px] table-fixed text-left text-sm">
          <colgroup>
            <col className="w-[22%]" />
            <col className="w-[20%]" />
            <col className="w-[18%]" />
            <col className="w-[20%]" />
            <col className="w-[20%]" />
          </colgroup>
          <thead className="bg-[#070b1b] text-xs text-[#bfc9e7]/56">
            <tr className="border-b border-white/10">
              <th className="px-4 py-3">所属环境</th>
              <th className="px-4 py-3">节点名称</th>
              <th className="px-4 py-3">CPU</th>
              <th className="px-4 py-3">内存</th>
              <th className="px-4 py-3">根目录</th>
            </tr>
          </thead>
          <tbody>
            {loadingTargets ? (
              <tr>
                <td className="px-4 py-12 text-center text-[#bfc9e7]/58" colSpan={5}>
                  加载中，正在读取已登记主机...
                </td>
              </tr>
            ) : null}

            {!loadingTargets && targets.length === 0 ? (
              <tr>
                <td className="px-4 py-12 text-center text-[#bfc9e7]/58" colSpan={5}>
                  {errorsByHost[0] || "请先在后台管理页面添加主机信息。"}
                </td>
              </tr>
            ) : null}

            {!loadingTargets && targets.length > 0 && visibleTargets.length === 0 ? (
              <tr>
                <td className="px-4 py-12 text-center text-[#bfc9e7]/58" colSpan={5}>
                  当前筛选条件下没有主机资源。
                </td>
              </tr>
            ) : null}

            {!loadingTargets ? visibleTargets.map((target) => {
              const inventory = inventories[target.host_id];
              const nodes = inventory?.nodes ?? [];
              const loading = Boolean(loadingByHost[target.host_id]);
              const error = errorsByHost[target.host_id];

              if (nodes.length === 0) {
                return (
                  <tr className="border-t border-white/15" key={target.host_id}>
                    <td className="bg-[#070b1b]/45 px-4 py-5 align-top">
                      <ResourceEnvironmentCell
                        error={error}
                        loading={loading}
                        nodeCount={0}
                        onRefresh={() => refreshHost(target.host_id)}
                        target={target}
                      />
                    </td>
                    <td className="px-4 py-8 text-center text-[#bfc9e7]/58" colSpan={4}>
                      {loading ? "加载中，正在读取节点和资源指标..." : error || "该环境未返回节点信息"}
                    </td>
                  </tr>
                );
              }

              return nodes.map((node, nodeIndex) => (
                <tr
                  className={`${nodeIndex === 0 ? "border-t border-white/15" : "border-t border-white/8"}`}
                  key={`${target.host_id}-${node.name}`}
                >
                  {nodeIndex === 0 ? (
                    <td className="bg-[#070b1b]/45 px-4 py-5 align-top" rowSpan={nodes.length}>
                      <ResourceEnvironmentCell
                        error={error}
                        loading={loading}
                        nodeCount={inventory.node_count}
                        onRefresh={() => refreshHost(target.host_id)}
                        target={target}
                      />
                    </td>
                  ) : null}
                  <td className="px-4 py-5 align-top">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="break-all font-black text-white">{node.name}</span>
                      <span className={`rounded-full px-2 py-1 text-[10px] font-bold ${node.ready ? "bg-[#0a1ae1]/40 text-[#9fb0ff]" : "bg-[#a30613]/30 text-[#ff9aa3]"}`}>
                        {node.ready ? "Ready" : "NotReady"}
                      </span>
                    </div>
                    {!node.metrics_available ? <p className="mt-2 break-words text-xs leading-5 text-[#ff9aa3]">{node.metrics_error || "暂无指标"}</p> : null}
                  </td>
                  <ResourceTableMetric
                    available={node.metrics_available}
                    detail={`${node.cpu.coreCount} 逻辑核 / ${node.cpu.window === "5m" ? "最近 5 分钟" : "实时采样"}`}
                    value={`${node.cpu.usagePercent}%`}
                  />
                  <ResourceTableMetric
                    available={node.metrics_available}
                    detail={`总量 ${node.memory.totalHuman} / 已用 ${node.memory.usedHuman} / 可用 ${node.memory.availableHuman}`}
                    value={`${node.memory.usagePercent}%`}
                  />
                  <ResourceTableMetric
                    available={node.metrics_available}
                    detail={`总量 ${node.rootDisk.totalHuman} / 已用 ${node.rootDisk.usedHuman} / 剩余 ${node.rootDisk.availableHuman}`}
                    value={`${node.rootDisk.usagePercent}%`}
                  />
                </tr>
              ));
            }) : null}
          </tbody>
        </table>
      </div>
    </SectionBlock>
  );
}

function ResourceEnvironmentCell({
  error,
  loading,
  nodeCount,
  onRefresh,
  target,
}: {
  error?: string;
  loading: boolean;
  nodeCount: number;
  onRefresh: () => void;
  target: ResourceHostOption;
}) {
  return (
    <div className="min-w-0">
      <p className="break-words font-black text-white">{target.environment_name || "未关联环境"}</p>
      <p className="mt-2 text-xs leading-5 text-[#bfc9e7]/58">
        {target.resource_mode === "k8s_cluster" ? `K8S 集群 · ${nodeCount} 个节点` : "独立主机 · node-exporter"}
      </p>
      <button
        className="mt-3 h-9 rounded-[6px] border border-[#4b5fc6] px-3 text-xs font-bold text-[#bfc9ff] transition hover:bg-[#0a1ae1]/24 disabled:cursor-not-allowed disabled:opacity-60"
        disabled={loading}
        onClick={onRefresh}
        type="button"
      >
        {loading ? "刷新中..." : "刷新指标"}
      </button>
      {error ? <p className="mt-3 break-words text-xs leading-5 text-[#ff9aa3]">{error}</p> : null}
    </div>
  );
}

function ResourceTableMetric({
  available,
  detail,
  value,
}: {
  available: boolean;
  detail: string;
  value: string;
}) {
  return (
    <td className="px-4 py-5 align-top">
      <p className="text-xl font-black text-white">{available ? value : "--"}</p>
      <p className="mt-2 break-words text-xs leading-5 text-[#bfc9e7]/58">{available ? detail : "暂无指标"}</p>
    </td>
  );
}

function DatabaseAccountInventoryView({ isSuperuser }: { isSuperuser: boolean }) {
  const [databaseType, setDatabaseType] = useState<"doris" | "mysql">("doris");
  const [instances, setInstances] = useState<DatabaseInstanceOption[]>([]);
  const [environmentName, setEnvironmentName] = useState("");
  const [instanceId, setInstanceId] = useState("");
  const [inventory, setInventory] = useState<DatabaseAccountInventory | null>(null);
  const [loadingInstances, setLoadingInstances] = useState(true);
  const [querying, setQuerying] = useState(false);
  const [error, setError] = useState("");
  const [passwordChecks, setPasswordChecks] = useState<Record<string, DatabasePasswordCheck>>({});
  const [managedPasswords, setManagedPasswords] = useState<Record<string, DatabaseManagedPasswordState>>({});

  const environments = useMemo(
    () => Array.from(new Set(instances.map((instance) => instance.environment_name))),
    [instances],
  );
  const environmentInstances = useMemo(
    () => instances.filter((instance) => instance.environment_name === environmentName),
    [environmentName, instances],
  );
  const databaseLabel = databaseType === "doris" ? "Doris" : "MySQL";

  function handleDatabaseTypeChange(nextType: "doris" | "mysql") {
    if (nextType === databaseType) {
      return;
    }
    setLoadingInstances(true);
    setInstances([]);
    setEnvironmentName("");
    setInstanceId("");
    setInventory(null);
    setPasswordChecks({});
    setManagedPasswords({});
    setError("");
    setDatabaseType(nextType);
  }

  useEffect(() => {
    const controller = new AbortController();
    fetchUserApi<DatabaseInstanceOption[]>(`/api/${databaseType}/instances`, controller.signal)
      .then((items) => {
        setInstances(items);
        const first = items[0];
        if (first) {
          setEnvironmentName(first.environment_name);
          setInstanceId(String(first.id));
        }
      })
      .catch((loadError) => {
        if (loadError instanceof DOMException && loadError.name === "AbortError") {
          return;
        }
        setError(loadError instanceof Error ? loadError.message : `${databaseLabel} 实例加载失败`);
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setLoadingInstances(false);
        }
      });
    return () => controller.abort();
  }, [databaseLabel, databaseType]);

  async function handleLoadAccounts() {
    if (!instanceId) {
      return;
    }
    setQuerying(true);
    setError("");
    setInventory(null);
    setPasswordChecks({});
    setManagedPasswords({});
    try {
      const result = await fetchUserApi<DatabaseAccountInventory>(
        `/api/${databaseType}/instances/${instanceId}/accounts`,
      );
      setInventory(result);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : `${databaseLabel} 账号列表获取失败`);
    } finally {
      setQuerying(false);
    }
  }

  function updateManagedPassword(
    userIdentity: string,
    patch: Partial<DatabaseManagedPasswordState>,
  ) {
    setManagedPasswords((current) => {
      const existing = current[userIdentity] ?? {
        value: "",
        visible: false,
        editing: false,
        status: "idle",
        message: "",
      };
      return {
        ...current,
        [userIdentity]: { ...existing, ...patch },
      };
    });
  }

  function markPasswordManaged(userIdentity: string, password: string) {
    updateManagedPassword(userIdentity, {
      value: password,
      visible: false,
      editing: false,
      status: "loaded",
      message: "",
    });
    setInventory((current) => current ? {
      ...current,
      accounts: current.accounts.map((account) => account.user_identity === userIdentity ? {
        ...account,
        password_managed: true,
        password_updated_at: new Date().toISOString(),
      } : account),
    } : current);
  }

  async function handleSaveManagedPassword(account: DatabaseAccount) {
    const current = managedPasswords[account.user_identity];
    if (!instanceId || !current?.value) {
      return;
    }
    updateManagedPassword(account.user_identity, { status: "loading", message: "" });
    try {
      const result = await mutateUserApi<{ saved: boolean; updated_at: string }>(
        `/api/${databaseType}/instances/${instanceId}/accounts/password/current`,
        "PUT",
        { user_identity: account.user_identity, password: current.value },
      );
      markPasswordManaged(account.user_identity, current.value);
      setInventory((inventory) => inventory ? {
        ...inventory,
        accounts: inventory.accounts.map((item) => item.user_identity === account.user_identity ? {
          ...item,
          password_managed: true,
          password_updated_at: result.updated_at,
          password_last_action: "manual",
        } : item),
      } : inventory);
      updateManagedPassword(account.user_identity, {
        editing: false,
        status: "loaded",
        message: "已保存，尚未校验",
      });
    } catch (saveError) {
      updateManagedPassword(account.user_identity, {
        status: "error",
        message: saveError instanceof Error ? saveError.message : "当前密码保存失败",
      });
    }
  }

  async function handleManagedPassword(
    account: DatabaseAccount,
    purpose: "view" | "copy",
  ) {
    const current = managedPasswords[account.user_identity];
    if (purpose === "view" && current?.status === "loaded") {
      updateManagedPassword(account.user_identity, {
        visible: !current.visible,
        message: "",
      });
      return;
    }

    updateManagedPassword(account.user_identity, { status: "loading", message: "" });
    try {
      const result = await mutateUserApi<{ password: string; updated_at: string }>(
        `/api/${databaseType}/instances/${instanceId}/accounts/password/current`,
        "POST",
        { user_identity: account.user_identity, purpose },
      );
      if (purpose === "copy") {
        await navigator.clipboard.writeText(result.password);
      }
      updateManagedPassword(account.user_identity, {
        value: result.password,
        visible: purpose === "view",
        status: "loaded",
        message: purpose === "copy" ? "已复制" : "",
      });
    } catch (managedError) {
      updateManagedPassword(account.user_identity, {
        status: "error",
        message: managedError instanceof Error ? managedError.message : "当前密码读取失败",
      });
    }
  }

  function updatePasswordCheck(userIdentity: string, patch: Partial<DatabasePasswordCheck>) {
    setPasswordChecks((current) => {
      const existing = current[userIdentity] ?? {
        password: "",
        status: "idle",
        message: "",
      };
      return {
        ...current,
        [userIdentity]: { ...existing, ...patch },
      };
    });
  }

  async function handleVerifyPassword(account: DatabaseAccount) {
    const check = passwordChecks[account.user_identity];
    if (!instanceId || !check?.password) {
      return;
    }
    updatePasswordCheck(account.user_identity, { status: "checking", message: "" });
    try {
      const result = await mutateUserApi<{ matched: boolean; managed_password_updated: boolean }>(
        `/api/${databaseType}/instances/${instanceId}/accounts/password/verify`,
        "POST",
        { user_identity: account.user_identity, password: check.password },
      );
      updatePasswordCheck(account.user_identity, {
        status: result.matched ? "matched" : "mismatch",
        message: result.matched ? "密码一致" : "密码不一致",
      });
      if (result.matched && result.managed_password_updated) {
        markPasswordManaged(account.user_identity, check.password);
      }
    } catch (verifyError) {
      updatePasswordCheck(account.user_identity, {
        status: "idle",
        message: verifyError instanceof Error ? verifyError.message : "密码校验失败",
      });
    }
  }

  async function handleResetPassword(account: DatabaseAccount) {
    const check = passwordChecks[account.user_identity];
    if (!instanceId || !check?.password || check.status !== "mismatch") {
      return;
    }
    updatePasswordCheck(account.user_identity, { status: "resetting", message: "" });
    try {
      await mutateUserApi<{ updated: boolean }>(
        `/api/${databaseType}/instances/${instanceId}/accounts/password`,
        "PUT",
        { user_identity: account.user_identity, password: check.password },
      );
      updatePasswordCheck(account.user_identity, {
        status: "matched",
        message: "已同步，密码一致",
      });
      markPasswordManaged(account.user_identity, check.password);
    } catch (resetError) {
      updatePasswordCheck(account.user_identity, {
        status: "mismatch",
        message: resetError instanceof Error ? resetError.message : "密码同步失败",
      });
    }
  }

  return (
    <SectionBlock title="数据库账号获取" description="按所属环境和实例实时查询 Doris 或 MySQL 账号信息。">
      <div className="mb-4 flex gap-2" role="group" aria-label="数据库类型">
        {(["doris", "mysql"] as const).map((type) => (
          <button
            aria-pressed={databaseType === type}
            className={`h-10 min-w-28 rounded-[6px] border px-4 text-sm font-bold transition ${
              databaseType === type
                ? "border-[#4b5fc6] bg-[#0a1ae1] text-white"
                : "border-[#1b255d] bg-[#070b1b] text-[#bfc9e7]/72 hover:border-[#4b5fc6] hover:text-white"
            }`}
            key={type}
            onClick={() => handleDatabaseTypeChange(type)}
            type="button"
          >
            {type === "doris" ? "Doris" : "MySQL"}
          </button>
        ))}
      </div>
      <div className="grid gap-4 rounded-[6px] border border-white/10 bg-[#070b1b] p-4 lg:grid-cols-[minmax(220px,0.8fr)_minmax(280px,1fr)_180px]">
        <label className="block">
          <span className="mb-2 block text-xs font-bold text-[#bfc9e7]/56">所属环境</span>
          <select
            className="h-11 w-full rounded-[6px] border border-[#1b255d] bg-[#04050b] px-3 text-sm text-white outline-none disabled:opacity-60"
            disabled={loadingInstances || environments.length === 0}
            onChange={(event) => {
              const nextEnvironment = event.target.value;
              const firstInstance = instances.find(
                (instance) => instance.environment_name === nextEnvironment,
              );
              setEnvironmentName(nextEnvironment);
              setInstanceId(firstInstance ? String(firstInstance.id) : "");
              setInventory(null);
              setManagedPasswords({});
              setError("");
            }}
            value={environmentName}
          >
            {environments.length === 0 ? <option value="">暂无已登记环境</option> : null}
            {environments.map((environment) => (
              <option key={environment} value={environment}>{environment}</option>
            ))}
          </select>
        </label>
        <label className="block">
          <span className="mb-2 block text-xs font-bold text-[#bfc9e7]/56">{databaseLabel} 实例</span>
          <select
            className="h-11 w-full rounded-[6px] border border-[#1b255d] bg-[#04050b] px-3 text-sm text-white outline-none disabled:opacity-60"
            disabled={loadingInstances || environmentInstances.length === 0}
            onChange={(event) => {
              setInstanceId(event.target.value);
              setInventory(null);
              setManagedPasswords({});
              setError("");
            }}
            value={instanceId}
          >
            {environmentInstances.length === 0 ? <option value="">暂无 {databaseLabel} 实例</option> : null}
            {environmentInstances.map((instance) => (
              <option key={instance.id} value={instance.id}>{instance.instance_name}</option>
            ))}
          </select>
        </label>
        <button
          className="h-11 self-end rounded-[6px] bg-[#0a1ae1] px-4 text-sm font-black text-white transition hover:bg-[#1628ff] disabled:cursor-not-allowed disabled:opacity-60"
          disabled={!instanceId || querying || loadingInstances}
          onClick={handleLoadAccounts}
          type="button"
        >
          {querying ? "正在查询..." : "获取账号列表"}
        </button>
      </div>

      {loadingInstances ? <p className="mt-5 border border-white/10 px-4 py-10 text-center text-sm text-[#bfc9e7]/64">正在加载已登记的 {databaseLabel} 实例...</p> : null}
      {!loadingInstances && instances.length === 0 && !error ? <p className="mt-5 border border-dashed border-white/14 px-4 py-10 text-center text-sm text-[#bfc9e7]/64">请先在后台管理页面添加 {databaseLabel} 连接信息。</p> : null}
      {error ? <p className="mt-5 rounded-[6px] border border-[#ff4d5d]/40 bg-[#a30613]/18 px-4 py-3 text-sm text-[#ff9aa3]">{error}</p> : null}
      {querying ? <p className="mt-5 border border-white/10 px-4 py-10 text-center text-sm text-[#bfc9e7]/64">正在连接 {databaseLabel} 并读取账号信息...</p> : null}

      {inventory && !querying ? (
        <div className="mt-5 overflow-x-auto">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-3 text-xs text-[#bfc9e7]/58">
            <span>{inventory.instance.environment_name} / {inventory.instance.instance_name}</span>
            <span>{inventory.account_count} 个账号</span>
          </div>
          <table className={`w-full text-left text-sm ${isSuperuser ? "min-w-[1980px]" : "min-w-[1120px]"}`}>
            <thead className="text-xs text-[#bfc9e7]/52">
              <tr className="border-b border-white/10">
                <th className="py-3 pr-5">用户名</th>
                <th className="py-3 pr-5">Host</th>
                <th className="py-3 pr-5">用户标识</th>
                <th className="py-3 pr-5">备注</th>
                {isSuperuser ? <th className="w-[500px] py-3 pr-5">当前密码</th> : null}
                {isSuperuser ? <th className="w-[460px] py-3">密码对比</th> : null}
              </tr>
            </thead>
            <tbody>
              {inventory.accounts.map((account) => {
                const check = passwordChecks[account.user_identity] ?? {
                  password: "",
                  status: "idle",
                  message: "",
                };
                const managed = managedPasswords[account.user_identity] ?? {
                  value: "",
                  visible: false,
                  editing: false,
                  status: "idle",
                  message: "",
                };
                const busy = check.status === "checking" || check.status === "resetting";
                return (
                  <tr className="border-b border-white/8 align-top text-[#bfc9e7]/78" key={account.user_identity}>
                    <td className="break-all py-4 pr-5 font-bold text-white">{account.username || "未识别"}</td>
                    <td className="break-all py-4 pr-5 font-mono text-xs">{account.host || "-"}</td>
                    <td className="break-all py-4 pr-5 font-mono text-xs text-[#9fb0ff]">{account.user_identity}</td>
                    <td className="break-words py-4 pr-5">{account.comment || "-"}</td>
                    {isSuperuser ? (
                      <td className="py-4 pr-5">
                        {account.password_managed && !managed.editing ? (
                          <>
                            <div className="flex min-h-10 items-start gap-2">
                              <input
                                autoComplete="off"
                                className="h-10 min-w-0 flex-1 rounded-[6px] border border-[#1b255d] bg-[#04050b] px-3 text-sm text-white outline-none"
                                placeholder="已托管"
                                readOnly
                                type={managed.visible ? "text" : "password"}
                                value={managed.value}
                              />
                              <button
                                className="h-10 shrink-0 rounded-[6px] border border-[#4b5fc6] px-3 text-xs font-bold text-[#bfc9e7] disabled:opacity-50"
                                disabled={managed.status === "loading"}
                                onClick={() => handleManagedPassword(account, "view")}
                                title={managed.visible ? "隐藏当前密码" : "显示当前密码"}
                                type="button"
                              >
                                {managed.status === "loading" ? "读取中" : managed.visible ? "隐藏" : "显示"}
                              </button>
                              <button
                                className="h-10 shrink-0 rounded-[6px] border border-[#4b5fc6] px-3 text-xs font-bold text-[#bfc9e7] disabled:opacity-50"
                                disabled={managed.status === "loading"}
                                onClick={() => handleManagedPassword(account, "copy")}
                                title="复制当前密码"
                                type="button"
                              >
                                复制
                              </button>
                              <button
                                className="h-10 shrink-0 rounded-[6px] border border-[#4b5fc6] px-3 text-xs font-bold text-[#bfc9e7] disabled:opacity-50"
                                disabled={managed.status === "loading"}
                                onClick={() => updateManagedPassword(account.user_identity, {
                                  value: "",
                                  visible: false,
                                  editing: true,
                                  status: "idle",
                                  message: "",
                                })}
                                title="手工更新平台登记的当前密码"
                                type="button"
                              >
                                更新
                              </button>
                            </div>
                            {account.password_updated_at ? (
                              <p className="mt-2 text-xs text-[#bfc9e7]/42">更新于 {formatDateTime(account.password_updated_at)}</p>
                            ) : null}
                            {managed.message ? (
                              <p className={`mt-2 text-xs ${managed.status === "error" ? "text-[#ff9aa3]" : "text-[#6ce5b1]"}`}>{managed.message}</p>
                            ) : null}
                          </>
                        ) : (
                          <>
                            <div className="flex min-h-10 items-start gap-2">
                              <input
                                autoComplete="new-password"
                                className="h-10 min-w-0 flex-1 rounded-[6px] border border-[#1b255d] bg-[#04050b] px-3 text-sm text-white outline-none focus:border-[#4b5fc6]"
                                disabled={managed.status === "loading"}
                                onChange={(event) => updateManagedPassword(account.user_identity, {
                                  value: event.target.value,
                                  visible: false,
                                  status: "idle",
                                  message: "",
                                })}
                                placeholder="输入当前密码"
                                type="password"
                                value={managed.value}
                              />
                              <button
                                className="h-10 shrink-0 rounded-[6px] bg-[#0a1ae1] px-3 text-xs font-bold text-white disabled:cursor-not-allowed disabled:opacity-50"
                                disabled={!managed.value || managed.status === "loading"}
                                onClick={() => handleSaveManagedPassword(account)}
                                type="button"
                              >
                                {managed.status === "loading" ? "保存中" : "保存"}
                              </button>
                              {account.password_managed ? (
                                <button
                                  className="h-10 shrink-0 rounded-[6px] border border-[#4b5fc6] px-3 text-xs font-bold text-[#bfc9e7]"
                                  onClick={() => updateManagedPassword(account.user_identity, {
                                    value: "",
                                    editing: false,
                                    status: "idle",
                                    message: "",
                                  })}
                                  type="button"
                                >
                                  取消
                                </button>
                              ) : null}
                            </div>
                            {managed.message ? <p className="mt-2 text-xs text-[#ff9aa3]">{managed.message}</p> : null}
                          </>
                        )}
                      </td>
                    ) : null}
                    {isSuperuser ? (
                      <td className="py-4">
                        <div className="flex min-h-10 items-start gap-2">
                          <input
                            autoComplete="new-password"
                            className="h-10 min-w-0 flex-1 rounded-[6px] border border-[#1b255d] bg-[#04050b] px-3 text-sm text-white outline-none focus:border-[#4b5fc6]"
                            disabled={busy}
                            onChange={(event) => updatePasswordCheck(account.user_identity, {
                              password: event.target.value,
                              status: "idle",
                              message: "",
                            })}
                            placeholder="输入曾发放的密码"
                            type="password"
                            value={check.password}
                          />
                          <button
                            className="h-10 shrink-0 rounded-[6px] border border-[#4b5fc6] px-3 text-xs font-bold text-[#bfc9e7] disabled:cursor-not-allowed disabled:opacity-50"
                            disabled={!check.password || busy}
                            onClick={() => handleVerifyPassword(account)}
                            type="button"
                          >
                            {check.status === "checking" ? "校验中..." : "对比"}
                          </button>
                          {check.status === "mismatch" || check.status === "resetting" ? (
                            <button
                              className="h-10 shrink-0 rounded-[6px] bg-[#a30613] px-3 text-xs font-bold text-white disabled:cursor-not-allowed disabled:opacity-50"
                              disabled={busy}
                              onClick={() => handleResetPassword(account)}
                              type="button"
                            >
                              {check.status === "resetting" ? "同步中..." : "同步此密码"}
                            </button>
                          ) : null}
                        </div>
                        {check.message ? (
                          <p className={`mt-2 text-xs ${check.status === "matched" ? "text-[#6ce5b1]" : "text-[#ff9aa3]"}`}>
                            {check.message}
                          </p>
                        ) : null}
                      </td>
                    ) : null}
                  </tr>
                );
              })}
              {inventory.accounts.length === 0 ? <tr><td className="py-10 text-center text-[#bfc9e7]/52" colSpan={isSuperuser ? 6 : 4}>该 {databaseLabel} 实例没有返回账号信息</td></tr> : null}
            </tbody>
          </table>
          <p className="mt-4 text-xs text-[#bfc9e7]/48">当前密码可以手工加密登记，也会在校验成功或同步修改后自动更新；手工登记不会修改 {databaseLabel} 密码。</p>
        </div>
      ) : null}
    </SectionBlock>
  );
}

function BusinessSystemView({
  activePage,
  onSetActivePage,
}: {
  activePage: BusinessPageKey;
  onSetActivePage: (page: BusinessPageKey) => void;
}) {
  const pages: Array<{ key: BusinessPageKey; label: string; hint: string }> = [
    { key: "nodePorts", label: "服务 NodePort", hint: "各环境对外端口" },
    { key: "imageTags", label: "镜像管理", hint: "按环境和 namespace 查看镜像" },
    { key: "gpuModels", label: "GPU 模型显存", hint: "模型、显存与空闲卡" },
    { key: "envKeys", label: "环境变量 key", hint: "只展示 key，不展示 value" },
  ];

  return (
    <div className="space-y-5">
      <SubPageNav activeKey={activePage} items={pages} onChange={onSetActivePage} />

      {activePage === "nodePorts" ? (
        <NodePortInventoryView />
      ) : null}

      {activePage === "imageTags" ? (
        <ImageInventoryView />
      ) : null}

      {activePage === "gpuModels" ? (
        <SectionBlock title="GPU 模型部署与显存" description="GPU 模型、显存占用与空闲卡位静态展示。">
          <CompactTable
            columns={["环境", "模型", "占用 GPU", "显存", "空闲卡"]}
            rows={gpuModelRows.map((row) => [row.env, row.model, row.gpu, row.memory, row.freeCard])}
          />
        </SectionBlock>
      ) : null}

      {activePage === "envKeys" ? (
        <EnvironmentKeyInventoryView />
      ) : null}
    </div>
  );
}

function NodePortInventoryView() {
  const [hosts, setHosts] = useState<K8sHostOption[]>([]);
  const [hostId, setHostId] = useState("");
  const [namespaces, setNamespaces] = useState<string[]>([]);
  const [namespace, setNamespace] = useState("");
  const [services, setServices] = useState<NodePortService[]>([]);
  const [loadingHosts, setLoadingHosts] = useState(true);
  const [loadingNamespaces, setLoadingNamespaces] = useState(false);
  const [querying, setQuerying] = useState(false);
  const [hasQueried, setHasQueried] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    fetchUserApi<K8sHostOption[]>("/api/k8s/nodeports/hosts", controller.signal)
      .then((rows) => {
        setHosts(rows);
        setLoadingNamespaces(rows.length > 0);
        setHostId(rows[0] ? String(rows[0].host_id) : "");
      })
      .catch((loadError) => {
        if (!(loadError instanceof DOMException && loadError.name === "AbortError")) {
          setError(loadError instanceof Error ? loadError.message : "所属环境加载失败");
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoadingHosts(false);
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!hostId) return;
    const controller = new AbortController();
    fetchUserApi<{ namespaces: string[] }>(
      `/api/k8s/nodeports/namespaces?host_id=${hostId}`,
      controller.signal,
    )
      .then((data) => {
        setNamespaces(data.namespaces);
        setNamespace(data.namespaces[0] ?? "");
      })
      .catch((loadError) => {
        if (!(loadError instanceof DOMException && loadError.name === "AbortError")) {
          setError(loadError instanceof Error ? loadError.message : "Namespace 加载失败");
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoadingNamespaces(false);
      });
    return () => controller.abort();
  }, [hostId]);

  async function queryNodePorts() {
    if (!hostId || !namespace) return;
    setQuerying(true);
    setHasQueried(false);
    setError("");
    try {
      const data = await fetchUserApi<{ services: NodePortService[] }>(
        `/api/k8s/nodeports?host_id=${hostId}&namespace=${encodeURIComponent(namespace)}`,
      );
      setServices(data.services.filter((service) => service.visible));
      setHasQueried(true);
    } catch (queryError) {
      setError(queryError instanceof Error ? queryError.message : "NodePort 查询失败");
    } finally {
      setQuerying(false);
    }
  }

  const selectedHost = hosts.find((host) => String(host.host_id) === hostId);
  const servicePortCounts = services.reduce<Record<string, number>>((counts, service) => {
    counts[service.service_name] = (counts[service.service_name] ?? 0) + 1;
    return counts;
  }, {});

  return (
    <SectionBlock title="服务 NodePort 公网调用地址" description="选择所属环境和 Namespace，查询当前 NodePort 类型 Service 的公网调用地址。">
      <div className="grid gap-4 rounded-[6px] border border-white/10 bg-[#070b1b] p-4 md:grid-cols-2 xl:grid-cols-[1.2fr_1fr_auto]">
        <label className="block">
          <span className="mb-2 block text-xs font-bold text-[#bfc9e7]/56">所属环境 / 主机</span>
          <select className="h-11 w-full rounded-[6px] border border-[#1b255d] bg-[#04050b] px-3 text-sm text-white outline-none disabled:opacity-60" disabled={loadingHosts || hosts.length === 0} onChange={(event) => {
            setError("");
            setNamespaces([]);
            setNamespace("");
            setServices([]);
            setHasQueried(false);
            setLoadingNamespaces(true);
            setHostId(event.target.value);
          }} value={hostId}>
            {hosts.length === 0 ? <option value="">暂无已配置 K8S 凭证的环境</option> : null}
            {hosts.map((host) => <option key={host.host_id} value={host.host_id}>{host.environment_name} / {host.hostname}</option>)}
          </select>
        </label>
        <label className="block">
          <span className="mb-2 block text-xs font-bold text-[#bfc9e7]/56">Namespace</span>
          <select className="h-11 w-full rounded-[6px] border border-[#1b255d] bg-[#04050b] px-3 text-sm text-white outline-none disabled:opacity-60" disabled={loadingNamespaces || namespaces.length === 0} onChange={(event) => {
            setError("");
            setServices([]);
            setHasQueried(false);
            setNamespace(event.target.value);
          }} value={namespace}>
            {loadingNamespaces ? <option value="">正在获取 Namespace...</option> : null}
            {!loadingNamespaces && namespaces.length === 0 ? <option value="">暂无可用 Namespace</option> : null}
            {namespaces.map((item) => <option key={item} value={item}>{item}</option>)}
          </select>
        </label>
        <button className="h-11 self-end rounded-[6px] bg-[#0a1ae1] px-5 text-sm font-black text-white disabled:cursor-not-allowed disabled:opacity-60" disabled={!namespace || querying || loadingNamespaces} onClick={queryNodePorts} type="button">
          {querying ? "正在查询..." : "获取 NodePort 地址"}
        </button>
      </div>

      <div className="mt-4 flex flex-wrap gap-3 text-xs text-[#bfc9e7]/58">
        <span>所属环境：{selectedHost?.environment_name ?? "未选择"}</span>
        <span>主机：{selectedHost?.hostname ?? "未选择"}</span>
        <span>公网 IP：{selectedHost?.public_ip || "未配置"}</span>
      </div>

      {error ? <p className="mt-4 rounded-[6px] border border-[#ff4d5d]/40 bg-[#a30613]/18 px-4 py-3 text-sm text-[#ff9aa3]">{error}</p> : null}
      {loadingHosts ? <p className="mt-5 rounded-[6px] border border-white/10 bg-[#070b1b] px-4 py-8 text-center text-sm text-[#bfc9e7]/64">正在加载已配置 K8S 凭证的环境...</p> : null}
      {!loadingHosts && !error && hosts.length === 0 ? <p className="mt-5 rounded-[6px] border border-dashed border-white/14 px-4 py-8 text-center text-sm text-[#bfc9e7]/64">暂无可查询的 K8S 环境。</p> : null}

      {hasQueried && !error ? (
        <div className="mt-5 overflow-x-auto">
          <table className="w-full min-w-[900px] text-left text-sm">
            <thead className="text-xs text-[#bfc9e7]/52">
              <tr className="border-b border-white/10">
                <th className="w-[32%] py-3 pr-5">调用名称</th>
                <th className="w-[18%] py-3 pr-5">端口名称</th>
                <th className="w-[28%] py-3 pr-5">公网调用地址</th>
                <th className="w-24 py-3 pr-5">协议</th>
                <th className="py-3 pr-4">注释</th>
              </tr>
            </thead>
            <tbody>
              {services.map((service) => {
                const hasMultiplePorts = servicePortCounts[service.service_name] > 1;
                const callName = `${service.service_display_name}服务公网调用地址${hasMultiplePorts ? `（${service.port_name}）` : ""}`;
                return (
                  <tr className="border-b border-white/8 text-[#bfc9e7]/78" key={`${service.service_name}-${service.port_name}-${service.node_port}`}>
                    <td className="py-4 pr-5 font-bold text-white">{callName}</td>
                    <td className="py-4 pr-5 font-mono text-xs text-[#9fb0ff]">{service.port_name}</td>
                    <td className="py-4 pr-5 font-mono text-sm font-bold text-white">{service.public_address ?? "未配置公网 IP"}</td>
                    <td className="py-4 pr-5">{service.protocol}</td>
                    <td className="py-4 pr-4">{service.note ?? "-"}</td>
                  </tr>
                );
              })}
              {services.length === 0 ? <tr><td className="py-10 text-center text-[#bfc9e7]/52" colSpan={5}>该 Namespace 当前没有 NodePort 类型的 Service</td></tr> : null}
            </tbody>
          </table>
        </div>
      ) : null}
    </SectionBlock>
  );
}

function EnvironmentKeyInventoryView() {
  const [hosts, setHosts] = useState<EnvK8sHostOption[]>([]);
  const [hostId, setHostId] = useState("");
  const [namespaces, setNamespaces] = useState<string[]>([]);
  const [namespace, setNamespace] = useState("");
  const [workloads, setWorkloads] = useState<EnvWorkload[]>([]);
  const [workloadKey, setWorkloadKey] = useState("");
  const [result, setResult] = useState<EnvKeyResult | null>(null);
  const [loadingHosts, setLoadingHosts] = useState(true);
  const [loadingNamespaces, setLoadingNamespaces] = useState(false);
  const [loadingWorkloads, setLoadingWorkloads] = useState(false);
  const [querying, setQuerying] = useState(false);
  const [resultRevision, setResultRevision] = useState(0);
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    fetchUserApi<EnvK8sHostOption[]>("/api/k8s/env/hosts", controller.signal)
      .then((rows) => {
        setHosts(rows);
        setLoadingNamespaces(rows.length > 0);
        setHostId(rows[0] ? String(rows[0].host_id) : "");
      })
      .catch((loadError) => {
        if (!(loadError instanceof DOMException && loadError.name === "AbortError")) {
          setError(loadError instanceof Error ? loadError.message : "所属环境加载失败");
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoadingHosts(false);
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!hostId) return;

    const controller = new AbortController();
    fetchUserApi<{ namespaces: string[] }>(`/api/k8s/env/namespaces?host_id=${hostId}`, controller.signal)
      .then((data) => {
        setNamespaces(data.namespaces);
        setLoadingWorkloads(data.namespaces.length > 0);
        setNamespace(data.namespaces[0] ?? "");
      })
      .catch((loadError) => {
        if (!(loadError instanceof DOMException && loadError.name === "AbortError")) {
          setError(loadError instanceof Error ? loadError.message : "Namespace 加载失败");
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoadingNamespaces(false);
      });
    return () => controller.abort();
  }, [hostId]);

  useEffect(() => {
    if (!hostId || !namespace) return;

    const controller = new AbortController();
    fetchUserApi<{ workloads: EnvWorkload[] }>(
      `/api/k8s/env/workloads?host_id=${hostId}&namespace=${encodeURIComponent(namespace)}`,
      controller.signal,
    )
      .then((data) => {
        setWorkloads(data.workloads);
        const first = data.workloads[0];
        setWorkloadKey(first ? `${first.kind}:${first.name}` : "");
      })
      .catch((loadError) => {
        if (!(loadError instanceof DOMException && loadError.name === "AbortError")) {
          setError(loadError instanceof Error ? loadError.message : "工作负载加载失败");
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoadingWorkloads(false);
      });
    return () => controller.abort();
  }, [hostId, namespace]);

  async function queryEnvironmentKeys() {
    const workload = workloads.find((item) => `${item.kind}:${item.name}` === workloadKey);
    if (!workload || !hostId || !namespace) return;
    setQuerying(true);
    setError("");
    setResult(null);
    try {
      const data = await fetchUserApi<EnvKeyResult>(
        `/api/k8s/env/keys?host_id=${hostId}&namespace=${encodeURIComponent(namespace)}&kind=${workload.kind}&workload=${encodeURIComponent(workload.name)}`,
      );
      setResult(data);
      setResultRevision((current) => current + 1);
    } catch (queryError) {
      setError(queryError instanceof Error ? queryError.message : "环境变量 Key 查询失败");
    } finally {
      setQuerying(false);
    }
  }

  const selectedHost = hosts.find((host) => String(host.host_id) === hostId);

  return (
    <SectionBlock title="环境变量 Key 列表" description="按后台配置的 Namespace 白名单查询任一 Running Pod。容器内只输出变量名称，接口不会返回 value。">
      <div className="grid gap-4 rounded-[6px] border border-white/10 bg-[#070b1b] p-4 md:grid-cols-2 xl:grid-cols-[1.1fr_0.8fr_1.2fr_auto]">
        <label className="block">
          <span className="mb-2 block text-xs font-bold text-[#bfc9e7]/56">所属环境 / 主机</span>
          <select className="h-11 w-full rounded-[6px] border border-[#1b255d] bg-[#04050b] px-3 text-sm text-white outline-none disabled:opacity-60" disabled={loadingHosts || hosts.length === 0} onChange={(event) => { setError(""); setNamespaces([]); setNamespace(""); setWorkloads([]); setWorkloadKey(""); setResult(null); setLoadingNamespaces(true); setHostId(event.target.value); }} value={hostId}>
            {hosts.length === 0 ? <option value="">暂无已开放环境</option> : null}
            {hosts.map((host) => <option key={host.host_id} value={host.host_id}>{host.environment_name} / {host.hostname}</option>)}
          </select>
        </label>
        <label className="block">
          <span className="mb-2 block text-xs font-bold text-[#bfc9e7]/56">Namespace</span>
          <select className="h-11 w-full rounded-[6px] border border-[#1b255d] bg-[#04050b] px-3 text-sm text-white outline-none disabled:opacity-60" disabled={loadingNamespaces || namespaces.length === 0} onChange={(event) => { setError(""); setWorkloads([]); setWorkloadKey(""); setResult(null); setLoadingWorkloads(true); setNamespace(event.target.value); }} value={namespace}>
            {loadingNamespaces ? <option value="">正在校验白名单...</option> : null}
            {!loadingNamespaces && namespaces.length === 0 ? <option value="">暂无可用 Namespace</option> : null}
            {namespaces.map((item) => <option key={item} value={item}>{item}</option>)}
          </select>
        </label>
        <label className="block">
          <span className="mb-2 block text-xs font-bold text-[#bfc9e7]/56">Deployment / StatefulSet</span>
          <select className="h-11 w-full rounded-[6px] border border-[#1b255d] bg-[#04050b] px-3 text-sm text-white outline-none disabled:opacity-60" disabled={loadingWorkloads || workloads.length === 0} onChange={(event) => { setError(""); setResult(null); setWorkloadKey(event.target.value); }} value={workloadKey}>
            {loadingWorkloads ? <option value="">正在加载工作负载...</option> : null}
            {!loadingWorkloads && workloads.length === 0 ? <option value="">暂无可用工作负载</option> : null}
            {workloads.map((item) => <option key={`${item.kind}:${item.name}`} value={`${item.kind}:${item.name}`}>{item.kind} / {item.name} ({item.ready_replicas}/{item.desired_replicas})</option>)}
          </select>
        </label>
        <button className="h-11 self-end rounded-[6px] bg-[#0a1ae1] px-5 text-sm font-black text-white disabled:cursor-not-allowed disabled:opacity-60" disabled={!workloadKey || querying || loadingWorkloads} onClick={queryEnvironmentKeys} type="button">
          {querying ? "正在查询..." : "获取 Key 列表"}
        </button>
      </div>

      <div className="mt-4 flex flex-wrap gap-3 text-xs text-[#bfc9e7]/58">
        <span>所属环境：{selectedHost?.environment_name ?? "未选择"}</span>
        <span>主机：{selectedHost?.hostname ?? "未选择"}</span>
        <span>白名单：{selectedHost?.namespace_keys.join(", ") || "未配置"}</span>
      </div>
      {error ? <p className="mt-4 rounded-[6px] border border-[#ff4d5d]/40 bg-[#a30613]/18 px-4 py-3 text-sm text-[#ff9aa3]">{error}</p> : null}
      {!loadingHosts && hosts.length === 0 && !error ? <p className="mt-5 rounded-[6px] border border-dashed border-white/14 px-4 py-8 text-center text-sm text-[#bfc9e7]/64">请先在后台管理页面为带 K8S 凭证的主机配置 Namespace Key 白名单。</p> : null}

      {result ? (
        <div className="mt-5 space-y-4">
          <div className="flex flex-wrap gap-4 border-b border-white/10 pb-4 text-sm text-[#bfc9e7]/68">
            <span>{result.workload.kind}：<strong className="font-mono text-white">{result.workload.name}</strong></span>
            <span>抽取 Pod：<strong className="font-mono text-white">{result.pod_name}</strong></span>
          </div>
          {result.containers.map((container) => (
            <EnvironmentKeyContainerList
              container={container}
              key={`${resultRevision}-${container.container_name}`}
            />
          ))}
        </div>
      ) : null}
    </SectionBlock>
  );
}

function EnvironmentKeyContainerList({
  container,
}: {
  container: EnvKeyResult["containers"][number];
}) {
  const [page, setPage] = useState(1);
  const [searchQuery, setSearchQuery] = useState("");
  const [caseSensitive, setCaseSensitive] = useState(false);
  const [prefixSearch, setPrefixSearch] = useState(false);
  const normalizedQuery = caseSensitive ? searchQuery.trim() : searchQuery.trim().toLowerCase();
  const filteredKeys = normalizedQuery
    ? container.keys.filter((key) => {
        const normalizedKey = caseSensitive ? key : key.toLowerCase();
        return prefixSearch ? normalizedKey.startsWith(normalizedQuery) : normalizedKey === normalizedQuery;
      })
    : container.keys;
  const totalPages = Math.max(1, Math.ceil(filteredKeys.length / environmentKeysPageSize));
  const safePage = Math.min(page, totalPages);
  const startIndex = (safePage - 1) * environmentKeysPageSize;
  const visibleKeys = filteredKeys.slice(startIndex, startIndex + environmentKeysPageSize);
  const pageNumbers = getVisiblePageNumbers(safePage, totalPages);

  return (
    <section
      className="rounded-[6px] border border-white/10 bg-[#070b1b] p-5"
      data-testid={`env-key-container-${container.container_name}`}
    >
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/10 pb-4">
        <h3 className="font-mono text-sm font-black text-white">容器：{container.container_name}</h3>
        <span className="text-xs text-[#bfc9e7]/52">
          {normalizedQuery ? `${filteredKeys.length} 个结果 / 共 ${container.keys.length} 个 Key` : `${container.keys.length} 个 Key`}
        </span>
      </div>

      {container.error ? <p className="mt-4 text-sm text-[#ff9aa3]">{container.error}</p> : null}
      {!container.error && container.keys.length === 0 ? <p className="py-8 text-center text-sm text-[#bfc9e7]/52">该容器未返回环境变量 Key</p> : null}
      {!container.error && container.keys.length > 0 ? (
        <>
          <div className="mt-4 flex flex-wrap items-end gap-4 border-b border-white/10 pb-4">
            <label className="min-w-[16rem] flex-1">
              <span className="mb-2 block text-xs font-bold text-[#bfc9e7]/56">搜索指定 Key</span>
              <input
                aria-label={`${container.container_name} 搜索指定 Key`}
                className="h-10 w-full rounded-[6px] border border-[#1b255d] bg-[#04050b] px-3 font-mono text-sm text-white outline-none placeholder:text-[#bfc9e7]/32 focus:border-[#4b5fc6]"
                onChange={(event) => {
                  setSearchQuery(event.target.value);
                  setPage(1);
                }}
                placeholder="输入完整 Key"
                type="search"
                value={searchQuery}
              />
            </label>
            <label className="flex h-10 cursor-pointer items-center gap-2 text-sm text-[#bfc9e7]/68">
              <input
                checked={caseSensitive}
                className="h-4 w-4 accent-[#0a1ae1]"
                onChange={(event) => {
                  setCaseSensitive(event.target.checked);
                  setPage(1);
                }}
                type="checkbox"
              />
              区分大小写
            </label>
            <label className="flex h-10 cursor-pointer items-center gap-2 text-sm text-[#bfc9e7]/68">
              <input
                checked={prefixSearch}
                className="h-4 w-4 accent-[#0a1ae1]"
                onChange={(event) => {
                  setPrefixSearch(event.target.checked);
                  setPage(1);
                }}
                type="checkbox"
              />
              前缀模糊搜索
            </label>
          </div>

          {filteredKeys.length === 0 ? (
            <p className="py-12 text-center text-sm font-bold text-[#bfc9e7]/58">没有任何结果、确定配置了吗？</p>
          ) : (
            <>
              <ol className="divide-y divide-white/8 border-b border-white/8">
                {visibleKeys.map((key, index) => (
                  <li className="grid min-h-11 grid-cols-[3rem_minmax(0,1fr)] items-center gap-3 py-2" key={key}>
                    <span className="text-right font-mono text-xs tabular-nums text-[#bfc9e7]/38">{startIndex + index + 1}</span>
                    <code className="break-all font-mono text-sm text-[#c7d0ef]">{key}</code>
                  </li>
                ))}
              </ol>

              <footer className="mt-4 flex flex-wrap items-center justify-between gap-3">
                <p className="text-xs text-[#bfc9e7]/48">
                  显示 {startIndex + 1}-{Math.min(startIndex + environmentKeysPageSize, filteredKeys.length)}，共 {filteredKeys.length} 条
                </p>
                <nav aria-label={`${container.container_name} Key 分页`} className="flex items-center gap-1">
                  <PaginationButton disabled={safePage === 1} label={`${container.container_name} 跳转到首页`} onClick={() => setPage(1)}>«</PaginationButton>
                  <PaginationButton disabled={safePage === 1} label={`${container.container_name} 上一页`} onClick={() => setPage((current) => Math.max(1, current - 1))}>‹</PaginationButton>
                  {pageNumbers[0] > 1 ? <span className="w-6 text-center text-xs text-[#bfc9e7]/36">…</span> : null}
                  {pageNumbers.map((pageNumber) => (
                    <button
                      aria-current={pageNumber === safePage ? "page" : undefined}
                      className={`h-8 min-w-8 border px-2 text-xs font-bold transition ${
                        pageNumber === safePage
                          ? "border-[#4b5fc6] bg-[#0a1ae1] text-white"
                          : "border-white/10 bg-[#04050b] text-[#bfc9e7]/64 hover:border-[#4b5fc6]/60 hover:text-white"
                      }`}
                      key={pageNumber}
                      onClick={() => setPage(pageNumber)}
                      type="button"
                    >
                      {pageNumber}
                    </button>
                  ))}
                  {pageNumbers.at(-1)! < totalPages ? <span className="w-6 text-center text-xs text-[#bfc9e7]/36">…</span> : null}
                  <PaginationButton disabled={safePage === totalPages} label={`${container.container_name} 下一页`} onClick={() => setPage((current) => Math.min(totalPages, current + 1))}>›</PaginationButton>
                  <PaginationButton disabled={safePage === totalPages} label={`${container.container_name} 跳转到末页`} onClick={() => setPage(totalPages)}>»</PaginationButton>
                  <span className="ml-2 min-w-20 text-right text-xs tabular-nums text-[#bfc9e7]/48">{safePage} / {totalPages} 页</span>
                </nav>
              </footer>
            </>
          )}
        </>
      ) : null}
    </section>
  );
}

function PaginationButton({
  children,
  disabled,
  label,
  onClick,
}: {
  children: React.ReactNode;
  disabled: boolean;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      aria-label={label}
      className="h-8 w-8 border border-white/10 bg-[#04050b] text-base text-[#bfc9e7]/68 transition hover:border-[#4b5fc6]/60 hover:text-white disabled:cursor-not-allowed disabled:opacity-30"
      disabled={disabled}
      onClick={onClick}
      title={label}
      type="button"
    >
      {children}
    </button>
  );
}

function getVisiblePageNumbers(currentPage: number, totalPages: number): number[] {
  const visibleCount = Math.min(5, totalPages);
  const start = Math.max(1, Math.min(currentPage - 2, totalPages - visibleCount + 1));
  return Array.from({ length: visibleCount }, (_, index) => start + index);
}

function ImageInventoryView() {
  const [hosts, setHosts] = useState<K8sHostOption[]>([]);
  const [hostId, setHostId] = useState("");
  const [namespaces, setNamespaces] = useState<string[]>([]);
  const [namespace, setNamespace] = useState("");
  const [images, setImages] = useState<ControllerImage[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingNamespaces, setLoadingNamespaces] = useState(false);
  const [querying, setQuerying] = useState(false);
  const [hasQueried, setHasQueried] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    fetchUserApi<K8sHostOption[]>("/api/k8s/hosts", controller.signal)
      .then((rows) => {
        setHosts(rows);
        setLoadingNamespaces(rows.length > 0);
        setHostId(rows[0] ? String(rows[0].host_id) : "");
        setLoading(false);
      })
      .catch((loadError) => {
        if (loadError instanceof Error && loadError.name !== "AbortError") {
          setError(loadError.message);
          setLoading(false);
        }
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!hostId) {
      return;
    }
    const controller = new AbortController();
    fetchUserApi<{ namespaces: string[] }>(`/api/k8s/namespaces?host_id=${hostId}`, controller.signal)
      .then((data) => {
        setNamespaces(data.namespaces);
        setNamespace(data.namespaces[0] ?? "");
        setLoadingNamespaces(false);
      })
      .catch((loadError) => {
        if (loadError instanceof Error && loadError.name !== "AbortError") {
          setError(loadError.message);
          setLoadingNamespaces(false);
        }
      });
    return () => controller.abort();
  }, [hostId]);

  async function queryImages() {
    if (!hostId || !namespace) {
      return;
    }
    setQuerying(true);
    setHasQueried(false);
    setError("");
    try {
      const data = await fetchUserApi<{ images: ControllerImage[] }>(
        `/api/k8s/images?host_id=${hostId}&namespace=${encodeURIComponent(namespace)}`,
      );
      setImages(data.images);
      setHasQueried(true);
    } catch (queryError) {
      setError(queryError instanceof Error ? queryError.message : "运行中镜像查询失败");
    } finally {
      setQuerying(false);
    }
  }

  const selectedHost = hosts.find((item) => String(item.host_id) === hostId);

  return (
    <SectionBlock title="镜像管理" description="选择已配置 K8S 凭证的环境主机和 namespace，再手动查询当前处于 Running 状态的 Pod 容器镜像。">
      <div className="grid gap-4 rounded-[6px] border border-white/10 bg-[#070b1b] p-4 md:grid-cols-2 xl:grid-cols-[1.2fr_1fr_auto]">
        <label className="block">
          <span className="mb-2 block text-xs font-bold text-[#bfc9e7]/56">环境 / 机器</span>
          <select className="h-11 w-full rounded-[6px] border border-[#1b255d] bg-[#04050b] px-3 text-sm text-white outline-none" disabled={hosts.length === 0} onChange={(event) => {
            setLoadingNamespaces(true);
            setError("");
            setNamespaces([]);
            setNamespace("");
            setImages([]);
            setHasQueried(false);
            setHostId(event.target.value);
          }} value={hostId}>
            {hosts.length === 0 ? <option value="">暂无已配置 K8S 凭证的主机</option> : null}
            {hosts.map((host) => <option key={host.host_id} value={host.host_id}>{host.environment_name} / {host.hostname}</option>)}
          </select>
        </label>
        <label className="block">
          <span className="mb-2 block text-xs font-bold text-[#bfc9e7]/56">Namespace</span>
          <select className="h-11 w-full rounded-[6px] border border-[#1b255d] bg-[#04050b] px-3 text-sm text-white outline-none" disabled={loadingNamespaces || namespaces.length === 0} onChange={(event) => {
            setError("");
            setImages([]);
            setHasQueried(false);
            setNamespace(event.target.value);
          }} value={namespace}>
            {loadingNamespaces ? <option value="">正在获取 namespace...</option> : null}
            {!loadingNamespaces && namespaces.length === 0 ? <option value="">暂无可用 namespace</option> : null}
            {namespaces.map((item) => <option key={item} value={item}>{item}</option>)}
          </select>
        </label>
        <button className="h-11 self-end rounded-[6px] bg-[#0a1ae1] px-5 text-sm font-black text-white disabled:cursor-not-allowed disabled:opacity-60" disabled={!namespace || querying || loadingNamespaces} onClick={queryImages} type="button">
          {querying ? "正在获取..." : "获取当前正在运行的镜像"}
        </button>
      </div>

      <div className="mt-4 flex flex-wrap gap-3 text-xs text-[#bfc9e7]/58">
        <span>当前环境：{selectedHost?.environment_name ?? "未选择"}</span>
        <span>当前机器：{selectedHost?.hostname ?? "未选择"}</span>
        <span>K8S 状态：{selectedHost?.status ?? "未选择"}</span>
      </div>

      {error ? <p className="mt-4 rounded-[6px] border border-[#ff4d5d]/40 bg-[#a30613]/18 px-4 py-3 text-sm text-[#ff9aa3]">{error}</p> : null}
      {loading ? <p className="mt-5 rounded-[6px] border border-white/10 bg-[#070b1b] px-4 py-8 text-center text-sm text-[#bfc9e7]/64">正在加载已配置 K8S 凭证的主机...</p> : null}
      {!loading && !error && hosts.length === 0 ? <p className="mt-5 rounded-[6px] border border-dashed border-white/14 px-4 py-8 text-center text-sm text-[#bfc9e7]/64">请先在后台管理页面为主机保存 K8S 凭证内容。</p> : null}

      {hasQueried && namespace && !error ? (
        <div className="mt-5 overflow-x-auto">
          <table className="w-full min-w-[1120px] text-left text-sm">
            <thead className="text-xs text-[#bfc9e7]/52"><tr className="border-b border-white/10"><th className="w-32 py-3 pr-5">控制器类型</th><th className="w-[19%] py-3 pr-5">控制器名称</th><th className="w-[24%] py-3 pr-5">Pod 名称</th><th className="w-32 py-3 pr-5">副本数（就绪/期望）</th><th className="w-[14%] py-3 pr-5">容器名</th><th className="py-3 pr-4">容器完整镜像</th></tr></thead>
            <tbody>
              {images.map((image) => (
                <tr className="border-b border-white/8 align-top text-[#bfc9e7]/78" key={`${image.controller_type}-${image.pod_name}`}>
                  <td className="py-4 pr-5 font-bold text-white">{image.controller_type}</td>
                  <td className="break-all py-4 pr-5 font-mono text-xs font-bold text-[#9fb0ff]">{image.controller_name}</td>
                  <td className="break-all py-4 pr-5 font-mono text-xs leading-6">{image.pod_name}</td>
                  <td className="py-4 pr-5 text-base font-black text-white">{image.ready_replicas}/{image.desired_replicas}</td>
                  <td className="py-4 pr-5 font-mono text-xs leading-6">
                    {image.containers.map((container) => <div key={`${container.name}-${container.image}`}>{container.name}</div>)}
                  </td>
                  <td className="py-4 pr-4 font-mono text-xs leading-6">
                    {image.containers.map((container) => <div className="break-all" key={`${container.name}-${container.image}`}>{container.image}</div>)}
                  </td>
                </tr>
              ))}
              {images.length === 0 ? <tr><td className="py-10 text-center text-[#bfc9e7]/52" colSpan={6}>该 namespace 当前没有 Deployment、StatefulSet 或 DaemonSet 的 Running Pod</td></tr> : null}
            </tbody>
          </table>
        </div>
      ) : null}
    </SectionBlock>
  );
}

async function fetchUserApi<T>(path: string, signal?: AbortSignal): Promise<T> {
  const session = readUserWebSession();
  if (!session) {
    throw new Error("用户端会话已失效，请重新登录");
  }
  const response = await fetch(`${apiBaseUrl}${path}`, {
    headers: { Authorization: `Bearer ${session.access_token}` },
    signal,
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail ?? `接口请求失败：${path}`);
  }
  return response.json() as Promise<T>;
}

async function mutateUserApi<T>(
  path: string,
  method: "POST" | "PUT",
  body: Record<string, unknown>,
): Promise<T> {
  const session = readUserWebSession();
  if (!session) {
    throw new Error("用户端会话已失效，请重新登录");
  }
  const response = await fetch(`${apiBaseUrl}${path}`, {
    method,
    headers: {
      Authorization: `Bearer ${session.access_token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail ?? `接口请求失败：${path}`);
  }
  return response.json() as Promise<T>;
}

function formatDateTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

function MiddlewareSystemView({
  activePage,
  onSetActivePage,
}: {
  activePage: MiddlewarePageKey;
  onSetActivePage: (page: MiddlewarePageKey) => void;
}) {
  const [nacosInstances, setNacosInstances] = useState<NacosInstanceOption[]>([]);
  const [selectedNacosId, setSelectedNacosId] = useState("");
  const [nacosCatalog, setNacosCatalog] = useState<NacosCatalog | null>(null);
  const [selectedNamespaceId, setSelectedNamespaceId] = useState("");
  const [nacosLoading, setNacosLoading] = useState(false);
  const [nacosInstancesLoading, setNacosInstancesLoading] = useState(true);
  const [nacosError, setNacosError] = useState("");
  const [nacosStructure, setNacosStructure] = useState<NacosConfigStructure | null>(null);
  const [nacosStructureLoading, setNacosStructureLoading] = useState(false);
  const [nacosStructureError, setNacosStructureError] = useState("");
  const [expandedNacosConfigKey, setExpandedNacosConfigKey] = useState("");
  const [mysqlDashboards, setMysqlDashboards] = useState<MysqlDashboardOption[]>([]);
  const [mysqlDashboardsLoading, setMysqlDashboardsLoading] = useState(false);
  const [mysqlDashboardError, setMysqlDashboardError] = useState("");
  const nacosStructureRequestId = useRef(0);
  const nacosTableScrollRef = useRef<HTMLDivElement>(null);

  function clearNacosStructure() {
    nacosStructureRequestId.current += 1;
    setExpandedNacosConfigKey("");
    setNacosStructure(null);
    setNacosStructureError("");
    setNacosStructureLoading(false);
  }

  useEffect(() => {
    const controller = new AbortController();
    fetchUserApi<NacosInstanceOption[]>("/api/nacos/instances", controller.signal)
      .then((items) => {
        setNacosInstances(items);
        setSelectedNacosId((current) => current || (items[0] ? String(items[0].id) : ""));
      })
      .catch((loadError) => {
        if (loadError instanceof DOMException && loadError.name === "AbortError") {
          return;
        }
        setNacosError(loadError instanceof Error ? loadError.message : "Nacos 环境加载失败");
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setNacosInstancesLoading(false);
        }
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (activePage !== "healthChecks") {
      return;
    }
    const controller = new AbortController();
    setMysqlDashboardsLoading(true);
    setMysqlDashboardError("");
    fetchUserApi<MysqlDashboardOption[]>("/api/mysql/dashboards", controller.signal)
      .then(setMysqlDashboards)
      .catch((loadError) => {
        if (loadError instanceof DOMException && loadError.name === "AbortError") {
          return;
        }
        setMysqlDashboardError(
          loadError instanceof Error ? loadError.message : "MySQL 仪表盘加载失败",
        );
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setMysqlDashboardsLoading(false);
        }
      });
    return () => controller.abort();
  }, [activePage]);

  async function handleLoadNacosCatalog() {
    if (!selectedNacosId) {
      return;
    }
    setNacosLoading(true);
    setNacosError("");
    setNacosCatalog(null);
    setSelectedNamespaceId("");
    clearNacosStructure();
    try {
      const catalog = await fetchUserApi<NacosCatalog>(
        `/api/nacos/instances/${selectedNacosId}/catalog`,
      );
      setNacosCatalog(catalog);
      setSelectedNamespaceId(catalog.namespaces[0]?.namespace_id ?? "");
    } catch (loadError) {
      setNacosError(loadError instanceof Error ? loadError.message : "Nacos 配置目录获取失败");
    } finally {
      setNacosLoading(false);
    }
  }

  async function handleLoadNacosStructure(config: {
    group: string;
    data_id: string;
    type: string;
  }) {
    if (!selectedNacosId || !selectedNamespace) {
      return;
    }
    const configKey = `${selectedNamespace.namespace_id}\u001f${config.group}\u001f${config.data_id}`;
    if (expandedNacosConfigKey === configKey) {
      clearNacosStructure();
      return;
    }
    const requestId = nacosStructureRequestId.current + 1;
    nacosStructureRequestId.current = requestId;
    setExpandedNacosConfigKey(configKey);
    window.requestAnimationFrame(() => {
      nacosTableScrollRef.current?.scrollTo({ left: 0, behavior: "smooth" });
    });
    setNacosStructureLoading(true);
    setNacosStructure(null);
    setNacosStructureError("");
    try {
      const structure = await mutateUserApi<NacosConfigStructure>(
        `/api/nacos/instances/${selectedNacosId}/config-structure`,
        "POST",
        {
          namespace_id: selectedNamespace.namespace_id,
          group: config.group,
          data_id: config.data_id,
          config_type: config.type,
        },
      );
      if (nacosStructureRequestId.current === requestId) {
        setNacosStructure(structure);
      }
    } catch (loadError) {
      if (nacosStructureRequestId.current === requestId) {
        setNacosStructureError(
          loadError instanceof Error ? loadError.message : "Nacos 配置结构获取失败",
        );
      }
    } finally {
      if (nacosStructureRequestId.current === requestId) {
        setNacosStructureLoading(false);
      }
    }
  }

  const pages: Array<{ key: MiddlewarePageKey; label: string; hint: string }> = [
    { key: "nacosKeys", label: "Nacos 配置目录", hint: "Namespace、Group 与配置名称" },
    { key: "healthChecks", label: "数据库可用性校验", hint: "MySQL、Doris、Redis、Kafka" },
  ];
  const selectedNamespace = nacosCatalog?.namespaces.find(
    (namespace) => namespace.namespace_id === selectedNamespaceId,
  ) ?? nacosCatalog?.namespaces[0];
  const configuredMysqlDashboards = mysqlDashboards.filter((item) => item.dashboard_url);

  return (
    <div className="space-y-5">
      <SubPageNav activeKey={activePage} items={pages} onChange={onSetActivePage} />

      {activePage === "nacosKeys" ? (
        <SectionBlock title="Nacos 配置目录" description="选择后台已登记的环境，查询 Namespace、Group、配置名称与格式；点击配置右侧的查看内容，在当前配置下方展开已清空 value 的结构。">
        <div className="grid gap-4 xl:grid-cols-[360px_1fr]">
          <div className="rounded-[6px] border border-white/10 bg-[#070b1b] p-4">
            <label className="block">
              <span className="mb-2 block text-xs font-bold text-[#bfc9e7]/56">环境</span>
              <select
                className="h-11 w-full rounded-[6px] border border-[#1b255d] bg-[#04050b] px-3 text-sm text-white outline-none disabled:opacity-60"
                disabled={nacosInstancesLoading || nacosInstances.length === 0}
                onChange={(event) => {
                  setSelectedNacosId(event.target.value);
                  setNacosCatalog(null);
                  setSelectedNamespaceId("");
                  setNacosError("");
                  clearNacosStructure();
                }}
                value={selectedNacosId}
              >
                {nacosInstances.length === 0 ? <option value="">暂无已登记环境</option> : null}
                {nacosInstances.map((instance) => (
                  <option key={instance.id} value={instance.id}>
                    {instance.environment_name}
                  </option>
                ))}
              </select>
            </label>
            <button
              className="mt-5 h-10 w-full rounded-[6px] bg-[#0a1ae1] px-4 text-sm font-black text-white disabled:opacity-60"
              disabled={!selectedNacosId || nacosLoading || nacosInstancesLoading}
              onClick={handleLoadNacosCatalog}
              type="button"
            >
              {nacosLoading ? "正在获取配置目录..." : "获取 Namespace 与配置"}
            </button>
            <p className="mt-3 text-xs leading-5 text-[#bfc9e7]/54">
              目录只返回元数据；配置正文仅在点击后由服务端解析，浏览器只接收脱敏结构。
            </p>
            {nacosError ? <p className="mt-4 rounded-[6px] border border-[#ff4d5d]/40 bg-[#a30613]/18 px-3 py-3 text-sm text-[#ff9aa3]">{nacosError}</p> : null}
          </div>
          <div className="min-w-0">
            {nacosInstancesLoading ? <p className="border border-white/10 px-4 py-10 text-center text-sm text-[#bfc9e7]/64">正在加载已登记的 Nacos 环境...</p> : null}
            {!nacosInstancesLoading && nacosInstances.length === 0 && !nacosError ? <p className="border border-dashed border-white/14 px-4 py-10 text-center text-sm text-[#bfc9e7]/64">请先在后台管理页面添加 Nacos 连接信息。</p> : null}
            {nacosLoading ? <p className="border border-white/10 px-4 py-10 text-center text-sm text-[#bfc9e7]/64">正在连接 Nacos 并读取配置目录...</p> : null}
            {nacosCatalog && !nacosLoading ? (
              <div className="border border-white/10 bg-[#070b1b]">
                <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/10 px-5 py-4">
                  <div>
                    <p className="text-sm font-black text-white">{nacosCatalog.instance.environment_name}</p>
                    <p className="mt-1 text-xs text-[#bfc9e7]/54">{nacosCatalog.namespace_count} 个 Namespace，{nacosCatalog.config_count} 个配置</p>
                  </div>
                  <span className="text-xs font-bold text-[#7dd3fc]">已连接</span>
                </div>
                {nacosCatalog.namespaces.length > 0 ? (
                  <div className="overflow-x-auto border-b border-white/10">
                    <div className="flex w-max min-w-full gap-2 px-5 py-3" role="tablist" aria-label="Nacos Namespace">
                      {nacosCatalog.namespaces.map((namespace) => {
                        const active = namespace.namespace_id === selectedNamespace?.namespace_id;
                        return (
                          <button
                            aria-selected={active}
                            className={`min-w-24 flex-1 rounded-[6px] border px-3 py-3 text-left transition ${
                              active
                                ? "border-[#4b5fc6] bg-[#0a1ae1] text-white"
                                : "border-white/10 bg-[#04050b] text-[#bfc9e7]/68 hover:border-[#4b5fc6]/60 hover:text-white"
                            }`}
                            key={namespace.namespace_id}
                            onClick={() => {
                              setSelectedNamespaceId(namespace.namespace_id);
                              clearNacosStructure();
                            }}
                            role="tab"
                            type="button"
                          >
                            <span className="block truncate text-sm font-black" title={namespace.namespace_name}>{namespace.namespace_name}</span>
                            <span className={`mt-1 block text-xs ${active ? "text-white/70" : "text-[#bfc9e7]/46"}`}>
                              {namespace.config_count} 个配置
                            </span>
                          </button>
                        );
                      })}
                    </div>
                  </div>
                ) : null}
                {selectedNamespace ? (
                  <section>
                    <div className="flex items-center justify-between gap-3 px-5 py-4">
                      <div>
                        <h3 className="text-sm font-black text-white">{selectedNamespace.namespace_name}</h3>
                        <p className="mt-1 font-mono text-xs text-[#bfc9e7]/46">{selectedNamespace.namespace_id}</p>
                      </div>
                      <span className="text-xs text-[#bfc9e7]/60">{selectedNamespace.config_count} 个配置</span>
                    </div>
                    <div className="overflow-x-auto px-5 pb-4" ref={nacosTableScrollRef}>
                      <table className="w-full min-w-[760px] text-left text-sm">
                        <thead className="text-xs text-[#bfc9e7]/52">
                          <tr className="border-b border-white/10">
                            <th className="w-[28%] py-3 pr-4">Group</th>
                            <th className="py-3 pr-4">配置名称</th>
                            <th className="w-24 py-3 pr-4">格式</th>
                            <th className="w-28 py-3 text-right">操作</th>
                          </tr>
                        </thead>
                        <tbody>
                          {selectedNamespace.configs.map((config) => {
                            const configKey = `${selectedNamespace.namespace_id}\u001f${config.group}\u001f${config.data_id}`;
                            const supported = ["yaml", "yml", "json"].includes(config.type.toLowerCase());
                            const expanded = expandedNacosConfigKey === configKey;
                            return (
                              <Fragment key={configKey}>
                                <tr className={`border-b border-white/8 text-[#bfc9e7]/78 ${expanded ? "bg-[#0a1028]" : ""}`}>
                                  <td className="break-all py-3 pr-4 font-mono text-xs">{config.group}</td>
                                  <td className="break-all py-3 pr-4 font-mono text-xs font-bold text-[#9fb0ff]">{config.data_id}</td>
                                  <td className="py-3 pr-4 text-xs uppercase">{config.type}</td>
                                  <td className="py-2 text-right">
                                    {supported ? (
                                      <button
                                        aria-expanded={expanded}
                                        className={`h-8 rounded-[6px] border px-3 text-xs font-bold transition ${
                                          expanded
                                            ? "border-[#4b5fc6] bg-[#0a1ae1] text-white"
                                            : "border-[#29356f] text-[#9fb0ff] hover:border-[#4b5fc6] hover:text-white"
                                        }`}
                                        onClick={() => handleLoadNacosStructure(config)}
                                        type="button"
                                      >
                                        {expanded ? "收起" : "查看内容"}
                                      </button>
                                    ) : (
                                      <button
                                        className="h-8 rounded-[6px] border border-white/8 px-3 text-xs text-[#bfc9e7]/34"
                                        disabled
                                        title="当前仅支持 YAML、YML 和 JSON"
                                        type="button"
                                      >
                                        暂不支持
                                      </button>
                                    )}
                                  </td>
                                </tr>
                                {expanded ? (
                                  <tr className="border-b border-[#29356f]/70">
                                    <td className="p-0" colSpan={4}>
                                      <div className="bg-[#04050b] px-4 py-4">
                                        {nacosStructureLoading ? (
                                          <p className="border border-white/10 px-4 py-8 text-center text-sm text-[#bfc9e7]/64">
                                            正在读取并脱敏配置结构...
                                          </p>
                                        ) : null}
                                        {nacosStructureError ? (
                                          <p className="rounded-[6px] border border-[#ff4d5d]/40 bg-[#a30613]/18 px-3 py-3 text-sm text-[#ff9aa3]">
                                            {nacosStructureError}
                                          </p>
                                        ) : null}
                                        {nacosStructure && !nacosStructureLoading ? (
                                          <div className="min-w-0 overflow-hidden rounded-[6px] border border-[#1b255d] bg-[#050817]">
                                            <div className="flex flex-wrap items-start justify-between gap-3 border-b border-white/10 px-4 py-3">
                                              <div className="min-w-0">
                                                <p className="break-all font-mono text-sm font-bold text-white">{nacosStructure.data_id}</p>
                                                <p className="mt-1 break-all font-mono text-xs text-[#bfc9e7]/54">
                                                  {nacosStructure.group} / {nacosStructure.format.toUpperCase()}
                                                </p>
                                              </div>
                                              <div className="flex items-center gap-3">
                                                <span className="text-xs font-bold text-[#7dd3fc]">{nacosStructure.key_count} 个 Key</span>
                                                <button
                                                  className="h-8 rounded-[6px] border border-[#29356f] px-3 text-xs font-bold text-[#9fb0ff] hover:border-[#4b5fc6] hover:text-white"
                                                  onClick={clearNacosStructure}
                                                  type="button"
                                                >
                                                  收起
                                                </button>
                                              </div>
                                            </div>
                                            <pre className="max-h-[520px] overflow-auto whitespace-pre p-4 font-mono text-xs leading-6 text-[#c9d2f0]">
                                              {nacosStructure.structure}
                                            </pre>
                                          </div>
                                        ) : null}
                                      </div>
                                    </td>
                                  </tr>
                                ) : null}
                              </Fragment>
                            );
                          })}
                          {selectedNamespace.configs.length === 0 ? <tr><td className="py-6 text-center text-[#bfc9e7]/52" colSpan={4}>该 Namespace 暂无配置</td></tr> : null}
                        </tbody>
                      </table>
                    </div>
                  </section>
                ) : <p className="px-5 py-10 text-center text-sm text-[#bfc9e7]/52">该 Nacos 暂无 Namespace</p>}
              </div>
            ) : null}
          </div>
        </div>
        </SectionBlock>
      ) : null}

      {activePage === "healthChecks" ? (
        <SectionBlock title="核心数据库可用性快速校验" description="可用性脚本仍为预留功能；MySQL 支持跳转后台登记的 Grafana 仪表盘。">
        <div className="grid gap-4 lg:grid-cols-2">
          {healthCheckRows.map((row) => (
            <div className="rounded-[6px] border border-white/10 bg-[#070b1b] p-5" key={row.middleware}>
              <div className="flex items-start justify-between gap-3">
                <h3 className="text-lg font-black text-white">{row.middleware}</h3>
                <span className="rounded-full bg-[#0a1ae1]/24 px-3 py-1 text-xs font-bold text-[#9fb0ff]">{row.status}</span>
              </div>
              <p className="mt-4 text-sm leading-6 text-[#bfc9e7]/70">{row.check}</p>
              <div className="mt-5 flex flex-wrap gap-3">
                <button className="h-10 rounded-[6px] border border-[#4b5fc6] px-4 text-sm font-bold text-[#bfc9e7] opacity-60" disabled type="button">
                  测试 {row.middleware} 是否正常
                </button>
                {row.middleware === "MySQL" ? (
                  configuredMysqlDashboards.map((dashboard) => (
                    <a
                      className="inline-flex min-h-10 items-center rounded-[6px] bg-[#0a1ae1] px-4 py-2 text-sm font-bold text-white transition hover:bg-[#2636ff]"
                      href={dashboard.dashboard_url ?? undefined}
                      key={dashboard.id}
                      rel="noreferrer"
                      target="_blank"
                    >
                      查看仪表盘：{dashboard.environment_name} / {dashboard.instance_name}
                    </a>
                  ))
                ) : null}
              </div>
              {row.middleware === "MySQL" && mysqlDashboardsLoading ? <p className="mt-3 text-xs text-[#bfc9e7]/58">正在加载 MySQL 仪表盘配置...</p> : null}
              {row.middleware === "MySQL" && mysqlDashboardError ? <p className="mt-3 text-xs text-[#ff9aa3]">{mysqlDashboardError}</p> : null}
              {row.middleware === "MySQL" && !mysqlDashboardsLoading && !mysqlDashboardError && configuredMysqlDashboards.length === 0 ? (
                <p className="mt-3 text-xs text-[#ffd37a]">暂无已配置的 Grafana 仪表盘地址。</p>
              ) : null}
            </div>
          ))}
        </div>
        </SectionBlock>
      ) : null}
    </div>
  );
}

function MonitoringIntegrationView() {
  return (
    <div className="space-y-5">
      <SectionBlock title="待接入监控能力" description="当前只先搭页面骨架，等数据源和权限边界明确后再接入真实 API。">
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          {monitoringCards.map((card) => (
            <div className="rounded-[6px] border border-white/10 bg-[#070b1b] p-5" key={card.title}>
              <p className="text-sm font-black text-white">{card.title}</p>
              <p className="mt-3 text-sm leading-6 text-[#bfc9e7]/64">{card.detail}</p>
              <div className="mt-5 h-2 rounded-full bg-[#11183c]">
                <div className="h-2 w-1/4 rounded-full bg-[#4b5fc6]" />
              </div>
            </div>
          ))}
        </div>
      </SectionBlock>

      <div className="rounded-[8px] border border-dashed border-white/14 bg-[#04050b]/52 p-8 text-center">
        <p className="text-lg font-black text-white">监控系统集成暂定</p>
        <p className="mx-auto mt-3 max-w-2xl text-sm leading-6 text-[#bfc9e7]/68">
          后续可以在这里接入 Prometheus 查询模板、Loki 日志检索、Alertmanager 告警流、Grafana 跳转和统一 SLO 面板。
        </p>
      </div>
    </div>
  );
}

function ImplementationPanel({ text }: { text: string }) {
  return (
    <section className="rounded-[8px] border border-[#4b5fc6]/30 bg-[#0712a3]/16 p-5">
      <p className="text-xs font-bold text-[#9fb0ff]">实现方式</p>
      <p className="mt-2 text-sm leading-6 text-[#bfc9e7]/76">{text}</p>
    </section>
  );
}

function SectionBlock({
  children,
  description,
  title,
}: {
  children: React.ReactNode;
  description?: string;
  title: string;
}) {
  return (
    <section className="rounded-[8px] border border-white/10 bg-[#04050b]/52 p-5 shadow-2xl backdrop-blur">
      <div className="mb-5">
        <h2 className="text-lg font-black text-white">{title}</h2>
        {description ? <p className="mt-2 text-sm leading-6 text-[#bfc9e7]/64">{description}</p> : null}
      </div>
      {children}
    </section>
  );
}

function SubPageNav<T extends string>({
  activeKey,
  items,
  onChange,
}: {
  activeKey: T;
  items: Array<{ key: T; label: string; hint: string }>;
  onChange: (key: T) => void;
}) {
  return (
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
      {items.map((item) => {
        const active = item.key === activeKey;
        return (
          <button
            className={`min-h-[82px] rounded-[8px] border p-4 text-left transition ${
              active
                ? "border-[#4b5fc6] bg-[#0a1ae1]/24 shadow-[0_12px_30px_rgba(10,26,225,0.18)]"
                : "border-white/10 bg-[#04050b]/52 hover:border-[#4b5fc6]/60 hover:bg-[#11183c]"
            }`}
            key={item.key}
            onClick={() => onChange(item.key)}
            type="button"
          >
            <span className="block text-sm font-black text-white">{item.label}</span>
            <span className="mt-2 block text-xs leading-5 text-[#bfc9e7]/62">{item.hint}</span>
          </button>
        );
      })}
    </div>
  );
}

function CompactTable({ columns, rows }: { columns: string[]; rows: string[][] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[720px] text-left text-sm">
        <thead className="text-xs text-[#bfc9e7]/52">
          <tr className="border-b border-white/10">
            {columns.map((column) => (
              <th className="py-3 pr-4" key={column}>{column}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr className="border-b border-white/8 text-[#bfc9e7]/78" key={row.join("|")}>
              {row.map((cell, index) => (
                <td className={`py-4 pr-4 ${index === 0 ? "font-bold text-white" : ""}`} key={`${cell}-${index}`}>
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function readUserWebSession(): UserWebSession | null {
  try {
    const rawSession = window.localStorage.getItem(userSessionStorageKey);
    if (!rawSession) {
      return null;
    }
    const session = JSON.parse(rawSession) as Partial<UserWebSession>;
    if (!session.access_token || session.client_type !== userWebClientType) {
      return null;
    }
    return { access_token: session.access_token, client_type: userWebClientType };
  } catch {
    return null;
  }
}
