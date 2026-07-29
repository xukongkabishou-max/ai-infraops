"use client";

import { FormEvent, useEffect, useState } from "react";

type UserWebSession = {
  access_token: string;
  client_type: "user_web";
};

type SectionKey = "machine" | "business" | "middleware" | "monitoring";
type MachinePageKey = "environmentApis" | "machineAccounts" | "middlewareAccounts";
type BusinessPageKey = "nodePorts" | "imageTags" | "gpuModels" | "envKeys";
type MiddlewarePageKey = "nacosKeys" | "healthChecks";

type K8sHostOption = {
  host_id: number;
  environment_id: number;
  environment_name: string;
  hostname: string;
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

const navigationItems: Array<{
  key: SectionKey;
  label: string;
  hint: string;
}> = [
  { key: "machine", label: "机器信息管理", hint: "主机、日志、K8S 事件、账号" },
  { key: "business", label: "业务系统管理", hint: "NodePort、镜像、模型、环境变量" },
  { key: "middleware", label: "中间件系统管理", hint: "Nacos、数据库可用性" },
  { key: "monitoring", label: "监控系统集成", hint: "待定能力预留" },
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
    title: "环境地址、机器账号与中间件账号",
    summary:
      "面向研发提供各环境常用查询地址和账号信息入口，避免反复询问运维；当前先按子页面拆开静态展示。",
    implementation: "地址信息当前先静态维护；机器账号后续通过 Linux API 获取；中间件账号后续通过对应中间件 API 获取。",
  },
  business: {
    eyebrow: "业务系统管理",
    title: "服务端口、镜像版本、GPU 模型与环境变量",
    summary:
      "展示各环境服务对外 NodePort、当前镜像 tag、GPU 环境模型部署状态、显存占用和空闲卡位，并列出服务环境变量 key。",
    implementation: "服务信息通过 K8S API 获取，GPU 信息通过 dcgm-exporter 获取，环境变量 key 后续由大模型按内部提示词提取。",
  },
  middleware: {
    eyebrow: "中间件系统管理",
    title: "配置 key 盘点与核心中间件可用性校验",
    summary:
      "展示 Nacos 当前配置 key，并为 MySQL、Doris、Redis、Kafka 等核心组件预留快速可用性校验入口。",
    implementation: "Nacos 配置 key 后续由大模型按内部提示词提取；数据库可用性通过脚本模拟读写、生产消费和删除流程。",
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

const environmentRows = [
  {
    env: "开发 GPU 环境",
    publicIp: "203.0.113.21",
    privateIp: "10.20.1.21",
    cpu: "72 核 / 18.4%",
    memory: "256 GiB / 剩余 148 GiB",
    disk: "1.8 TiB / 剩余 820 GiB",
    loki: "/api/logs/loki/query?env=dev-gpu",
    k8s: "/api/k8s/events?cluster=dev-gpu",
  },
  {
    env: "测试 GPU 环境",
    publicIp: "203.0.113.32",
    privateIp: "10.30.1.32",
    cpu: "48 核 / 12.8%",
    memory: "192 GiB / 剩余 116 GiB",
    disk: "1.7 TiB / 剩余 795 GiB",
    loki: "/api/logs/loki/query?env=test-gpu",
    k8s: "/api/k8s/events?cluster=test-gpu",
  },
  {
    env: "生产 CPU 环境",
    publicIp: "203.0.113.45",
    privateIp: "10.40.1.45",
    cpu: "64 核 / 21.5%",
    memory: "128 GiB / 剩余 74 GiB",
    disk: "900 GiB / 剩余 410 GiB",
    loki: "/api/logs/loki/query?env=prod-cpu",
    k8s: "/api/k8s/events?cluster=prod-cpu",
  },
];

const machineAccountRows = [
  { env: "开发环境 GPU", hostGroup: "dev-gpu-*", username: "dev_reader", password: "******", privilege: "只读巡检" },
  { env: "测试环境 GPU", hostGroup: "test-gpu-*", username: "test_ops", password: "******", privilege: "运维执行" },
  { env: "生产环境 CPU", hostGroup: "prod-cpu-*", username: "prod_readonly", password: "******", privilege: "只读审计" },
];

const middlewareAccountRows = [
  { env: "生产环境", middleware: "RDS", instance: "core-business-db", username: "biz_reader", password: "******", privilege: "只读" },
  { env: "测试环境", middleware: "Milvus", instance: "vector-search", username: "milvus_test", password: "******", privilege: "读写测试库" },
  { env: "开发环境", middleware: "Redis", instance: "session-cache", username: "session_runtime", password: "******", privilege: "指定 DB 读写" },
  { env: "测试环境", middleware: "Kafka", instance: "event-bus", username: "ops_consumer", password: "******", privilege: "测试 Topic 消费" },
];

const nodePortRows = [
  { env: "开发 GPU 环境", namespace: "ai-serving", service: "model-gateway", nodePort: "32080", protocol: "HTTP" },
  { env: "开发 GPU 环境", namespace: "infra", service: "nacos-console", nodePort: "31848", protocol: "HTTP" },
  { env: "测试 GPU 环境", namespace: "observability", service: "grafana", nodePort: "31610", protocol: "HTTP" },
  { env: "生产 CPU 环境", namespace: "backend", service: "api-gateway", nodePort: "30080", protocol: "HTTP" },
];

const gpuModelRows = [
  { env: "开发 GPU 环境", model: "Qwen-72B-Instruct", gpu: "GPU-0, GPU-1", memory: "68 GiB / 96 GiB", freeCard: "GPU-2" },
  { env: "测试 GPU 环境", model: "Embedding-BGE", gpu: "GPU-3", memory: "18 GiB / 48 GiB", freeCard: "GPU-0, GPU-1" },
  { env: "生产 GPU 环境", model: "Rerank-Service", gpu: "GPU-5", memory: "9 GiB / 24 GiB", freeCard: "待接入" },
];

const envKeyRows = [
  { service: "model-gateway", keys: ["MODEL_NAME", "CUDA_VISIBLE_DEVICES", "SERVICE_PORT", "LOG_LEVEL"] },
  { service: "rag-api", keys: ["VECTOR_STORE", "MILVUS_COLLECTION", "REQUEST_TIMEOUT", "CACHE_TTL"] },
  { service: "ops-api", keys: ["MYSQL_DATABASE", "REDIS_DB", "KAFKA_TOPIC", "NACOS_NAMESPACE"] },
];

const nacosRows = [
  { namespace: "dev-gpu", group: "DEFAULT_GROUP", key: "model-gateway.yaml", owner: "AI 平台" },
  { namespace: "test-gpu", group: "DEFAULT_GROUP", key: "rag-api.yaml", owner: "知识库服务" },
  { namespace: "prod-cpu", group: "INFRA_GROUP", key: "ops-api.yaml", owner: "运维平台" },
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
      .then(() => {
        if (alive) {
          setAuthenticated(true);
        }
      })
      .catch(() => {
        window.localStorage.removeItem(userSessionStorageKey);
        if (alive) {
          setAuthenticated(false);
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
      const loginSession = data as UserWebSession;
      window.localStorage.setItem(
        userSessionStorageKey,
        JSON.stringify({
          access_token: loginSession.access_token,
          client_type: userWebClientType,
        }),
      );
      setAuthenticated(true);
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
  }

  if (authenticated) {
    const meta = sectionMeta[activeSection];

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
              {navigationItems.map((item) => {
                const active = item.key === activeSection;
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
              {activeSection === "machine" ? (
                <MachineInformationView
                  activePage={activeMachinePage}
                  onSetActivePage={setActiveMachinePage}
                />
              ) : null}
              {activeSection === "business" ? (
                <BusinessSystemView activePage={activeBusinessPage} onSetActivePage={setActiveBusinessPage} />
              ) : null}
              {activeSection === "middleware" ? (
                <MiddlewareSystemView activePage={activeMiddlewarePage} onSetActivePage={setActiveMiddlewarePage} />
              ) : null}
              {activeSection === "monitoring" ? <MonitoringIntegrationView /> : null}
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
  onSetActivePage,
}: {
  activePage: MachinePageKey;
  onSetActivePage: (page: MachinePageKey) => void;
}) {
  const pages: Array<{ key: MachinePageKey; label: string; hint: string }> = [
    { key: "environmentApis", label: "环境 API 地址", hint: "资源、日志、Pod 状态和事件查询地址" },
    { key: "machineAccounts", label: "机器账号列表", hint: "各环境 Linux 机器账号" },
    { key: "middlewareAccounts", label: "中间件账号获取", hint: "RDS、Milvus、Redis、Kafka 等账号" },
  ];

  return (
    <div className="space-y-5">
      <SubPageNav activeKey={activePage} items={pages} onChange={onSetActivePage} />

      {activePage === "environmentApis" ? (
        <SectionBlock title="环境 API 地址查询" description="这里不做资源查询功能，只给研发展示各环境可用的查询地址；手动维护还是自动同步后续再定。">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[980px] text-left text-sm">
              <thead className="text-xs text-[#bfc9e7]/52">
                <tr className="border-b border-white/10">
                  <th className="py-3 pr-4">环境</th>
                  <th className="py-3 pr-4">CPU / 内存 / 根目录磁盘</th>
                  <th className="py-3 pr-4">公网 / 私网 IP</th>
                  <th className="py-3 pr-4">Loki 日志 API</th>
                  <th className="py-3 pr-4">K8S Pod 状态与事件 API</th>
                </tr>
              </thead>
              <tbody>
                {environmentRows.map((row) => (
                  <tr className="border-b border-white/8 text-[#bfc9e7]/78" key={row.env}>
                    <td className="py-4 pr-4 font-bold text-white">{row.env}</td>
                    <td className="py-4 pr-4">
                      <p>CPU：{row.cpu}</p>
                      <p className="mt-1">内存：{row.memory}</p>
                      <p className="mt-1">磁盘：{row.disk}</p>
                    </td>
                    <td className="py-4 pr-4">
                      <p>公网：{row.publicIp}</p>
                      <p className="mt-1 text-[#bfc9e7]/54">私网：{row.privateIp}</p>
                    </td>
                    <td className="py-4 pr-4 font-mono text-xs text-[#9fb0ff]">{row.loki}</td>
                    <td className="py-4 pr-4 font-mono text-xs text-[#9fb0ff]">{row.k8s}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </SectionBlock>
      ) : null}

      {activePage === "machineAccounts" ? (
        <SectionBlock title="各环境机器账号列表" description="示例展示为脱敏密码。真实接入后仅对运维内部授权用户展示。">
          <CompactTable
            columns={["环境", "机器范围", "用户名", "密码", "权限说明"]}
            rows={machineAccountRows.map((row) => [row.env, row.hostGroup, row.username, row.password, row.privilege])}
          />
        </SectionBlock>
      ) : null}

      {activePage === "middlewareAccounts" ? (
        <SectionBlock title="中间件账号获取" description="示例展示为脱敏密码。后续由各中间件 API 或管理后台同步已创建账号。">
        <CompactTable
          columns={["环境", "中间件", "实例", "用户名", "密码", "权限说明"]}
          rows={middlewareAccountRows.map((row) => [row.env, row.middleware, row.instance, row.username, row.password, row.privilege])}
        />
        </SectionBlock>
      ) : null}
    </div>
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
        <SectionBlock title="各环境服务 NodePort 对外端口" description="除新疆联通外，各环境服务对外 NodePort 端口静态展示。">
        <CompactTable
          columns={["环境", "命名空间", "服务", "NodePort", "协议"]}
          rows={nodePortRows.map((row) => [row.env, row.namespace, row.service, row.nodePort, row.protocol])}
        />
        </SectionBlock>
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
        <SectionBlock title="环境变量 key 提取" description="只展示 key，不展示 value；后续通过内部提示词限定大模型提取范围。">
          <div className="space-y-3">
            {envKeyRows.map((row) => (
              <div className="rounded-[6px] border border-white/10 bg-[#070b1b] p-4" key={row.service}>
                <p className="text-sm font-bold text-white">{row.service}</p>
                <div className="mt-3 flex flex-wrap gap-2">
                  {row.keys.map((key) => (
                    <span className="rounded-full border border-[#4b5fc6]/42 px-3 py-1 text-xs font-mono text-[#bfc9e7]/78" key={key}>
                      {key}
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </SectionBlock>
      ) : null}
    </div>
  );
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
    fetchApi<K8sHostOption[]>("/api/k8s/hosts", controller.signal)
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
    fetchApi<{ namespaces: string[] }>(`/api/k8s/namespaces?host_id=${hostId}`, controller.signal)
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
      const data = await fetchApi<{ images: ControllerImage[] }>(
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

async function fetchApi<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${apiBaseUrl}${path}`, { signal });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail ?? `接口请求失败：${path}`);
  }
  return response.json() as Promise<T>;
}

function MiddlewareSystemView({
  activePage,
  onSetActivePage,
}: {
  activePage: MiddlewarePageKey;
  onSetActivePage: (page: MiddlewarePageKey) => void;
}) {
  const pages: Array<{ key: MiddlewarePageKey; label: string; hint: string }> = [
    { key: "nacosKeys", label: "Nacos key 获取", hint: "点击按钮请求后端 Codex 链路" },
    { key: "healthChecks", label: "数据库可用性校验", hint: "MySQL、Doris、Redis、Kafka" },
  ];

  return (
    <div className="space-y-5">
      <SubPageNav activeKey={activePage} items={pages} onChange={onSetActivePage} />

      {activePage === "nacosKeys" ? (
        <SectionBlock title="获取某个环境的 Nacos 所有 key" description="当前只是 mock 静态页面。后续研发点击按钮后，后端收到环境与服务信息，请求 Codex 再根据 skill 获取并隐藏所有 value，只返回 key 列表。">
        <div className="grid gap-4 xl:grid-cols-[360px_1fr]">
          <div className="rounded-[6px] border border-white/10 bg-[#070b1b] p-4">
            <label className="block">
              <span className="mb-2 block text-xs font-bold text-[#bfc9e7]/56">环境</span>
              <select className="h-11 w-full rounded-[6px] border border-[#1b255d] bg-[#04050b] px-3 text-sm text-white outline-none">
                <option>测试环境</option>
                <option>开发环境</option>
                <option>生产环境</option>
              </select>
            </label>
            <label className="mt-4 block">
              <span className="mb-2 block text-xs font-bold text-[#bfc9e7]/56">服务</span>
              <input className="h-11 w-full rounded-[6px] border border-[#1b255d] bg-[#04050b] px-3 text-sm text-white outline-none" readOnly value="ecmas-server" />
            </label>
            <button className="mt-5 h-10 w-full rounded-[6px] bg-[#0a1ae1] px-4 text-sm font-black text-white disabled:opacity-60" disabled type="button">
              获取 Nacos key 列表
            </button>
            <p className="mt-3 text-xs leading-5 text-[#bfc9e7]/54">静态阶段按钮禁用，后续接入后端请求链路。</p>
          </div>
          <div>
        <CompactTable
          columns={["命名空间", "Group", "配置 key", "归属"]}
          rows={nacosRows.map((row) => [row.namespace, row.group, row.key, row.owner])}
        />
          </div>
        </div>
        </SectionBlock>
      ) : null}

      {activePage === "healthChecks" ? (
        <SectionBlock title="核心数据库可用性快速校验" description="当前只是 mock 静态页面。后续前端点击测试 Kafka/MySQL/Doris/Redis，后端收到请求后执行对应模拟脚本。">
        <div className="grid gap-4 lg:grid-cols-2">
          {healthCheckRows.map((row) => (
            <div className="rounded-[6px] border border-white/10 bg-[#070b1b] p-5" key={row.middleware}>
              <div className="flex items-start justify-between gap-3">
                <h3 className="text-lg font-black text-white">{row.middleware}</h3>
                <span className="rounded-full bg-[#0a1ae1]/24 px-3 py-1 text-xs font-bold text-[#9fb0ff]">{row.status}</span>
              </div>
              <p className="mt-4 text-sm leading-6 text-[#bfc9e7]/70">{row.check}</p>
              <button className="mt-5 h-10 rounded-[6px] border border-[#4b5fc6] px-4 text-sm font-bold text-[#bfc9e7] opacity-60" disabled type="button">
                测试 {row.middleware} 是否正常
              </button>
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
