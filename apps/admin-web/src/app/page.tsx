"use client";

import { FormEvent, useEffect, useState } from "react";

type HostRecord = {
  id: number;
  hostname: string;
  public_ip: string;
  private_ip: string;
  node_exporter_url: string;
  status: "active" | "unreachable";
  last_error?: string | null;
  last_seen_at?: string | null;
};

type HostMetrics = {
  host: HostRecord;
  metrics: {
    load5: number;
    cpu: {
      coreCount: number;
      load5: number;
      load5Percent: number;
      usagePercent: number;
      sampleSeconds: number;
    };
    memory: {
      totalHuman: string;
      usedHuman: string;
      freeHuman: string;
      availableHuman: string;
      usagePercent: number;
    };
    rootDisk: {
      totalHuman: string;
      usedHuman: string;
      availableHuman: string;
      usagePercent: number;
    };
  };
};

type UserWebSession = {
  access_token: string;
  client_type: "user_web";
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
  const [authenticated, setAuthenticated] = useState(
    () => typeof window !== "undefined" && readUserWebSession() !== null,
  );
  const [hosts, setHosts] = useState<HostRecord[]>([]);
  const [selectedHostId, setSelectedHostId] = useState<number | null>(null);
  const [hostMetrics, setHostMetrics] = useState<HostMetrics | null>(null);
  const [metricsLoading, setMetricsLoading] = useState(false);
  const [metricsError, setMetricsError] = useState("");

  useEffect(() => {
    let alive = true;
    const savedSession = readUserWebSession();
    if (!authenticated || !savedSession) {
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
        return response.json() as Promise<HostRecord[]>;
      })
      .then(() => fetchJson<HostRecord[]>("/api/hosts"))
      .then((rows) => {
        if (alive) {
          setHosts(rows);
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
  }, [authenticated]);

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
      await loadHosts();
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
    setSelectedHostId(null);
    setHostMetrics(null);
  }

  async function toggleMetrics(hostId: number) {
    if (selectedHostId === hostId) {
      setSelectedHostId(null);
      setHostMetrics(null);
      setMetricsError("");
      return;
    }

    setSelectedHostId(hostId);
    setHostMetrics(null);
    setMetricsError("");
    setMetricsLoading(true);
    try {
      const data = await fetchJson<HostMetrics>(`/api/hosts/${hostId}/metrics`);
      setHostMetrics(data);
      await loadHosts();
    } catch (hostError) {
      setMetricsError(hostError instanceof Error ? hostError.message : "指标获取失败");
    } finally {
      setMetricsLoading(false);
    }
  }

  if (authenticated) {
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
                <p className="text-xs text-[#4b5fc6]">统一运维控制中心</p>
              </div>
            </div>

            <nav>
              <button
                className="h-11 w-full rounded-[6px] bg-[#0a1ae1] px-4 text-left text-sm font-bold text-white shadow-[0_12px_30px_rgba(10,26,225,0.28)]"
                type="button"
              >
                机器资源信息
              </button>
            </nav>
          </aside>

          <section className="min-w-0 bg-[radial-gradient(circle_at_75%_5%,rgba(10,26,225,0.30),transparent_30%),linear-gradient(135deg,#04050b_0%,#050e58_100%)]">
            <header className="flex flex-wrap items-center justify-between gap-4 border-b border-white/10 px-6 py-5 lg:px-8">
              <div>
                <p className="text-sm font-semibold text-[#4b5fc6]">机器资源信息</p>
                <h1 className="mt-1 text-2xl font-black tracking-normal">已添加主机</h1>
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
              <section className="space-y-4">
                {hosts.map((host) => (
                  <article
                    className="rounded-[8px] border border-white/10 bg-[#04050b]/52 p-5 shadow-2xl backdrop-blur"
                    key={host.id}
                  >
                    <div className="grid gap-5 xl:grid-cols-[330px_1fr]">
                      <div className="flex flex-col justify-between gap-5 border-white/10 xl:border-r xl:pr-5">
                        <div>
                          <div className="flex items-start justify-between gap-3">
                            <h2 className="text-lg font-black">主机名：{host.hostname || "未命名主机"}</h2>
                            <span
                              className={`shrink-0 rounded-full px-3 py-1 text-xs font-bold ${
                                host.status === "active"
                                  ? "bg-[#0a1ae1]/30 text-[#9fb0ff]"
                                  : "bg-[#a30613]/24 text-[#ff6b76]"
                              }`}
                            >
                              {host.status === "active" ? "活跃" : "无法连接"}
                            </span>
                          </div>
                          <p className="mt-3 text-sm text-[#bfc9e7]/70">公网 IP：{host.public_ip || "-"}</p>
                          <p className="mt-1 text-sm text-[#bfc9e7]/70">私网 IP：{host.private_ip || "未填写"}</p>
                          <p className="mt-4 break-all text-xs text-[#bfc9e7]/54">{host.node_exporter_url}</p>
                        </div>
                        <button
                          className="h-10 w-fit rounded-[6px] border border-[#4b5fc6] px-4 text-sm font-bold text-[#bfc9e7] transition hover:bg-[#11183c]"
                          onClick={() => toggleMetrics(host.id)}
                          type="button"
                        >
                          {selectedHostId === host.id ? "收起指标" : "查看指标"}
                        </button>
                      </div>

                      <div className="min-w-0">
                        {selectedHostId === host.id ? (
                          <>
                            {metricsLoading ? (
                              <p className="text-sm text-[#bfc9e7]/70">正在获取指标...</p>
                            ) : null}
                            {metricsError ? (
                              <p className="rounded-[6px] border border-[#ff4b57]/40 bg-[#a30613]/18 px-4 py-3 text-sm text-[#ff9aa3]">
                                {metricsError}
                              </p>
                            ) : null}
                            {hostMetrics ? (
                              <div className="grid gap-4 lg:grid-cols-3">
                                <MetricCard
                                  label="CPU 使用率"
                                  value={`${hostMetrics.metrics.cpu.usagePercent}%`}
                                  detail={`${hostMetrics.metrics.cpu.coreCount} 逻辑核 / 采样约 ${hostMetrics.metrics.cpu.sampleSeconds} 秒`}
                                />
                                <MetricCard
                                  label="内存使用率"
                                  value={`${hostMetrics.metrics.memory.usagePercent}%`}
                                  detail={`已用 ${hostMetrics.metrics.memory.usedHuman} / 空闲 ${hostMetrics.metrics.memory.freeHuman} / 可用 ${hostMetrics.metrics.memory.availableHuman}`}
                                />
                                <MetricCard
                                  label="/ 目录磁盘使用率"
                                  value={`${hostMetrics.metrics.rootDisk.usagePercent}%`}
                                  detail={`总量 ${hostMetrics.metrics.rootDisk.totalHuman} / 已用 ${hostMetrics.metrics.rootDisk.usedHuman} / 剩余 ${hostMetrics.metrics.rootDisk.availableHuman}`}
                                />
                              </div>
                            ) : null}
                          </>
                        ) : (
                          <div className="grid h-full min-h-[120px] place-items-center rounded-[6px] border border-dashed border-white/10 text-sm text-[#bfc9e7]/48">
                            点击查看指标后在这里横向展示 CPU、内存和磁盘使用率
                          </div>
                        )}
                      </div>
                    </div>
                  </article>
                ))}
              </section>
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

function MetricCard({ label, value, detail }: { label: string; value: string; detail?: string }) {
  return (
    <div className="rounded-[6px] border border-white/10 bg-[#070b1b] p-4">
      <p className="text-xs font-bold text-[#bfc9e7]/56">{label}</p>
      <p className="mt-3 text-2xl font-black text-white">{value}</p>
      {detail ? <p className="mt-2 text-xs leading-5 text-[#bfc9e7]/64">{detail}</p> : null}
    </div>
  );
}
