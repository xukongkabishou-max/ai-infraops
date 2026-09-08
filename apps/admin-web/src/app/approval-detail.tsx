"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { UserValueRequests } from "./value-requests";

type Session = { access_token: string; client_type: "user_web" };
const storageKey = "ai-infraops:user-web-session";
const inputClass = "mt-2 h-11 w-full rounded-[6px] border border-white/20 bg-[#04050b] px-3 text-white";

function savedSession(): Session | null {
  try {
    const session = JSON.parse(window.sessionStorage.getItem(storageKey) || "null");
    return session?.client_type === "user_web" && typeof session.access_token === "string" ? session : null;
  } catch { return null; }
}

async function readDetailApi<T>(path: string, signal?: AbortSignal): Promise<T> {
  const session = savedSession();
  if (!session) throw new Error("登录已失效，请重新登录");
  const response = await fetch(path, { signal, cache: "no-store", headers: { Authorization: `Bearer ${session.access_token}` } });
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "申请加载失败");
  return data as T;
}

async function mutateDetailApi<T>(path: string, method: "POST" | "PUT", body: Record<string, unknown>): Promise<T> {
  const session = savedSession();
  if (!session) throw new Error("登录已失效，请重新登录");
  const response = await fetch(path, { method, headers: { Authorization: `Bearer ${session.access_token}`, "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "审批失败");
  return data as T;
}

export function ApprovalDetailPage({ requestId }: { requestId: number }) {
  const [session, setSession] = useState<Session | null>(null);
  const [restoring, setRestoring] = useState(true);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    async function restore() {
      const saved = savedSession();
      try {
        if (!saved) return;
        const response = await fetch("/api/auth/session", { method: "POST", signal: controller.signal, headers: { "Content-Type": "application/json" }, body: JSON.stringify(saved) });
        if (!response.ok) throw new Error("session expired");
        const data = await response.json();
        if (!controller.signal.aborted) { setSession(saved); setDisplayName(data.user.username); }
      } catch {
        if (!controller.signal.aborted) window.sessionStorage.removeItem(storageKey);
      } finally { if (!controller.signal.aborted) setRestoring(false); }
    }
    void restore();
    return () => controller.abort();
  }, []);
  async function login(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      const response = await fetch("/api/auth/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username, password, client_type: "user_web" }) });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "登录失败");
      const saved: Session = { access_token: data.access_token, client_type: "user_web" };
      window.sessionStorage.setItem(storageKey, JSON.stringify(saved));
      setSession(saved); setDisplayName(data.user.username);
    } catch (e) { setError(e instanceof Error ? e.message : "登录失败"); }
    finally { setBusy(false); setPassword(""); }
  }
  function logout() {
    const saved = savedSession();
    window.sessionStorage.removeItem(storageKey); setSession(null); setUsername(""); setPassword(""); setError("");
    if (saved) void fetch("/api/auth/logout", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(saved) }).catch(() => undefined);
  }
  return <main className="min-h-screen bg-[#04050b] text-white">
    <header className="border-b border-white/10 px-5 py-5 sm:px-8">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4">
        <div><Link href="/" className="text-xs text-[#9fb0ff]">InfraOps 运维控制台</Link><h1 className="mt-2 text-xl font-bold">审批申请 #{requestId}</h1></div>
        {session ? <div className="flex items-center gap-4 text-sm"><span>{displayName}</span><button type="button" className="rounded-[6px] border border-[#4b5fc6] px-3 py-2" onClick={logout}>切换账号</button></div> : null}
      </div>
    </header>
    <div className="mx-auto max-w-6xl px-5 py-6 sm:px-8">
      {restoring ? <p className="text-sm text-[#bfc9e7]">正在验证登录状态...</p> : session ?
        <UserValueRequests key={`${session.access_token}:${requestId}`} requestId={requestId} read={readDetailApi} mutate={mutateDetailApi} /> :
        <form onSubmit={login} className="mx-auto mt-8 max-w-sm space-y-5">
          <h2 className="text-lg font-bold">登录查看申请</h2>
          <label className="block text-sm">账号<input autoComplete="username" required className={inputClass} value={username} onChange={event => setUsername(event.target.value)} /></label>
          <label className="block text-sm">密码<input autoComplete="current-password" required type="password" className={inputClass} value={password} onChange={event => setPassword(event.target.value)} /></label>
          {error ? <p role="alert" className="text-sm text-red-300">{error}</p> : null}
          <button className="h-11 w-full rounded-[6px] bg-[#0a1ae1] font-bold disabled:opacity-50" disabled={busy}>{busy ? "登录中..." : "登录并查看申请"}</button>
        </form>}
    </div>
  </main>;
}
