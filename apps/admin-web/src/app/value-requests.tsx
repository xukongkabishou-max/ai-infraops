"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";

type Category = "environment" | "nacos";
type ReadApi = <T>(path: string, signal?: AbortSignal) => Promise<T>;
type WriteApi = <T>(path: string, method: "POST" | "PUT", body: Record<string, unknown>) => Promise<T>;
type RequestRecord = {
  id: number; category: Category; environment_name: string; resource_name: string;
  target: Record<string, string | number>; reason: string; status: string;
  created_at: string; reviewed_at: string | null; captured_at: string | null;
  expires_at: string | null; reviewer_name: string | null; review_note: string;
};
type Snapshot = { snapshot: { value: string; pod_name?: string; container_name?: string; key?: string }; captured_at: string; expires_at: string; server_now: string };
const control = "min-h-9 rounded-[6px] border border-[#4b5fc6] px-3 py-2 text-xs font-bold text-[#c9d2f0] disabled:opacity-40";
const statusLabels: Record<string, string> = { pending: "待审批", approved: "已通过", rejected: "已拒绝", expired: "已过期" };
const time = (value: string | null) => value ? new Date(value).toLocaleString("zh-CN", { hour12: false }) : "-";

export function ValueRequestButton({ target, label, mutate }: { target: Record<string, unknown>; label: string; mutate: WriteApi }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true); setError("");
    try {
      const result = await mutate<{ id: number }>("/api/value-requests", "POST", { ...target, reason });
      setMessage(`申请 #${result.id} 已提交，待管理员审批`);
      dialog.current?.close(); setReason("");
    } catch (e) { setError(e instanceof Error ? e.message : "申请失败"); }
    finally { setBusy(false); }
  }
  return <div className="flex flex-wrap items-center justify-end gap-2 text-left">
    <button type="button" className={control} onClick={() => { setError(""); dialog.current?.showModal(); }}>查看具体 Value</button>
    {message ? <span role="status" className="text-xs text-emerald-300">{message}</span> : null}
    <dialog ref={dialog} className="m-auto w-[min(560px,calc(100vw-32px))] rounded-[6px] border border-[#4b5fc6] bg-[#070b1b] p-6 text-white backdrop:bg-black/70">
      <form onSubmit={submit} className="space-y-4">
        <h3 className="text-lg font-bold">申请查看 Value</h3>
        <p className="break-all text-sm text-[#c9d2f0]">{label}</p>
        <label className="block text-sm">申请原因<textarea autoFocus required maxLength={1000} value={reason} onChange={e => setReason(e.target.value)} className="mt-2 min-h-24 w-full rounded-[6px] border border-white/20 bg-[#04050b] p-3" /></label>
        {error ? <p role="alert" className="text-sm text-red-300">{error}</p> : null}
        <div className="flex justify-end gap-3"><button type="button" className={control} onClick={() => dialog.current?.close()}>取消</button><button className={`${control} bg-[#0a1ae1]`} disabled={busy || !reason.trim()}>{busy ? "提交中..." : "提交审批"}</button></div>
      </form>
    </dialog>
  </div>;
}

export function UserValueRequests({ category, read }: { category: Category; read: ReadApi }) {
  const [rows, setRows] = useState<RequestRecord[]>([]);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [revision, setRevision] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [values, setValues] = useState<Record<number, Snapshot>>({});
  const [busy, setBusy] = useState<number | null>(null);
  const [clock, setClock] = useState(() => Date.now());
  const clockOffset = useRef(0);
  const generation = useRef(0);
  const invalidate = useCallback(() => { generation.current++; }, []);
  const reload = useCallback(() => { generation.current++; setValues({}); setLoading(true); setRevision(v => v + 1); }, []);
  useEffect(() => {
    const controller = new AbortController();
    const load = () => read<{ items: RequestRecord[]; total: number; server_now: string }>(`/api/value-requests?category=${category}&page=${page}`, controller.signal)
      .then(data => { if (!controller.signal.aborted) { clockOffset.current = Date.parse(data.server_now) - Date.now(); setClock(Date.parse(data.server_now)); setRows(data.items); setTotal(data.total); setError(""); } })
      .catch(e => { if (!controller.signal.aborted) { setValues({}); setRows([]); setError(e instanceof Error ? e.message : "加载失败"); } })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    void load();
    const interval = window.setInterval(load, 15000);
    return () => { controller.abort(); window.clearInterval(interval); invalidate(); };
  }, [category, page, revision, read, invalidate]);
  useEffect(() => {
    const timer = window.setInterval(() => {
      const now = Date.now() + clockOffset.current; setClock(now);
      setValues(current => Object.fromEntries(Object.entries(current).filter(([, item]) => Date.parse(item.expires_at) > now)));
    }, 1000);
    return () => window.clearInterval(timer);
  }, []);
  async function reveal(row: RequestRecord) {
    const current = generation.current;
    setBusy(row.id); setError("");
    try {
      const data = await read<Snapshot>(`/api/value-requests/${row.id}/value`);
      if (current === generation.current) { setClock(Date.parse(data.server_now)); setValues(values => ({ ...values, [row.id]: data })); }
    } catch (e) { if (current === generation.current) setError(e instanceof Error ? e.message : "读取失败"); }
    finally { setBusy(null); }
  }
  return <section className="min-w-0 space-y-4 border-t border-white/10 pt-5">
    <div className="flex items-center justify-between gap-3"><h2 className="text-lg font-black">我的审批记录</h2><button className={control} onClick={reload}>刷新</button></div>
    {error ? <p role="alert" className="text-sm text-red-300">{error}</p> : null}
    {loading ? <p className="text-sm text-[#bfc9e7]">正在加载...</p> : rows.length === 0 ? <p className="py-10 text-center text-[#bfc9e7]">暂无申请记录</p> : null}
    <div className="divide-y divide-white/10">
      {rows.map(row => {
        const expired = row.expires_at !== null && Date.parse(row.expires_at) <= clock;
        const status = expired && row.status === "approved" ? "expired" : row.status;
        const snapshot = !expired && status === "approved" ? values[row.id] : undefined;
        return <article key={row.id} className="min-w-0 space-y-3 py-5">
          <div className="flex flex-wrap items-start justify-between gap-3"><div className="min-w-0"><h3 className="break-all text-sm font-bold">#{row.id} · {row.environment_name} / {row.resource_name}</h3><p className="mt-2 break-all font-mono text-xs text-[#bfc9e7]">{Object.entries(row.target).map(([key, value]) => `${key}: ${value}`).join(" · ")}</p></div><span className={`shrink-0 text-sm ${status === "approved" ? "text-emerald-300" : status === "pending" ? "text-yellow-300" : "text-[#bfc9e7]"}`}>{statusLabels[status] ?? status}</span></div>
          <p className="break-all text-sm text-[#bfc9e7]">申请原因：{row.reason}</p>
          <div className="flex flex-wrap gap-x-6 gap-y-2 text-xs text-[#bfc9e7]"><span>申请时间：{time(row.created_at)}</span><span>审批人：{row.reviewer_name ?? "-"}</span><span>审批时间：{time(row.reviewed_at)}</span><span>采集时间：{time(row.captured_at)}</span><span>有效期至：{time(row.expires_at)}</span></div>
          {row.review_note ? <p className="break-all text-sm text-[#bfc9e7]">审批备注：{row.review_note}</p> : null}
          {status === "approved" ? <button className={control} disabled={busy !== null} onClick={() => snapshot ? setValues(current => { const next = { ...current }; delete next[row.id]; return next; }) : reveal(row)}>{busy === row.id ? "读取中..." : snapshot ? "隐藏 Value" : "查看已批准的 Value"}</button> : null}
          {snapshot ? <div className="min-w-0 border-l-2 border-emerald-400 pl-4"><p className="mb-2 break-all text-xs text-emerald-300">数值采集于 {time(snapshot.captured_at)}{snapshot.snapshot.pod_name ? ` · Pod: ${snapshot.snapshot.pod_name} · 容器: ${snapshot.snapshot.container_name}` : ""}</p><pre className="max-h-[520px] overflow-auto whitespace-pre-wrap break-all bg-[#04050b] p-4 font-mono text-xs leading-6">{snapshot.snapshot.value === "" ? "（空字符串）" : snapshot.snapshot.value}</pre></div> : null}
        </article>;
      })}
    </div>
    <div className="flex items-center justify-end gap-3 text-xs"><span>共 {total} 条 · 第 {page} 页</span><button className={control} disabled={page <= 1} onClick={() => { reload(); setPage(page-1); }}>上一页</button><button className={control} disabled={page * 20 >= total} onClick={() => { reload(); setPage(page+1); }}>下一页</button></div>
  </section>;
}
