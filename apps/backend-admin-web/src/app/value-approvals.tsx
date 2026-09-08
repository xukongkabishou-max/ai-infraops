"use client";

import { FormEvent, useEffect, useRef, useState } from "react";

type Approval = {
  id: number; requester_name: string; requester_id: number; category: string;
  environment_name: string; resource_name: string; target: Record<string, unknown>;
  reason: string; status: string; created_at: string; reviewed_at: string | null;
  captured_at: string | null; expires_at: string | null; reviewer_name: string | null; review_note: string;
};
const control = "min-h-10 rounded-[6px] border border-[#4b5fc6] bg-[#070b1b] px-3 py-2 text-sm text-[#c9d2f0] disabled:opacity-40";
const time = (value: string | null) => value ? new Date(value).toLocaleString("zh-CN", { hour12: false }) : "-";
const labels: Record<string, string> = { pending: "待审批", approved: "已通过", rejected: "已拒绝", expired: "已过期" };

export function ValueApprovals({ accessToken, apiBaseUrl }: { accessToken: string; apiBaseUrl: string }) {
  const [rows, setRows] = useState<Approval[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [category, setCategory] = useState("");
  const [status, setStatus] = useState("");
  const [revision, setRevision] = useState(0);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<Approval | null>(null);
  const [decision, setDecision] = useState("approved");
  const [note, setNote] = useState("");
  const [minutes, setMinutes] = useState(60);
  const [busy, setBusy] = useState(false);
  const [reviewError, setReviewError] = useState("");
  const [notice, setNotice] = useState("");
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const controller = new AbortController();
    const query = new URLSearchParams({ page: String(page) });
    if (category) query.set("category", category);
    if (status) query.set("status", status);
    const load = async () => {
      try {
        const response = await fetch(`${apiBaseUrl}/api/admin/value-requests?${query}`, { headers: { Authorization: `Bearer ${accessToken}` }, cache: "no-store", signal: controller.signal });
        const data = await response.json();
        if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "加载失败");
        if (!controller.signal.aborted) { setRows(data.items); setTotal(data.total); setError(""); }
      } catch (e) { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : "加载失败"); }
      finally { if (!controller.signal.aborted) setLoading(false); }
    };
    void load();
    const interval = window.setInterval(load, 15000);
    return () => { controller.abort(); window.clearInterval(interval); };
  }, [accessToken, apiBaseUrl, category, status, page, revision]);
  function openReview(row: Approval) {
    setSelected(row); setNote(""); setMinutes(60); setDecision("approved"); setReviewError("");
    dialog.current?.showModal();
  }
  async function review(event: FormEvent) {
    event.preventDefault();
    if (!selected || busy) return;
    setBusy(true); setReviewError("");
    try {
      const response = await fetch(`${apiBaseUrl}/api/admin/value-requests/${selected.id}/review`, {
        method: "POST", headers: { Authorization: `Bearer ${accessToken}`, "Content-Type": "application/json" },
        body: JSON.stringify({ decision, note, validity_minutes: decision === "approved" ? minutes : 60 }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "审批失败");
      setNotice(`申请 #${selected.id} ${labels[data.status]}`); dialog.current?.close(); setRevision(v => v+1);
    } catch (e) { setReviewError(e instanceof Error ? e.message : "审批失败"); }
    finally { setBusy(false); }
  }
  return <section className="min-w-0 space-y-5">
    <div className="flex flex-wrap items-end gap-4">
      <label className="text-xs text-[#bfc9e7]">申请类别<select className={`${control} mt-2 block`} value={category} onChange={e => { setRows([]); setLoading(true); setPage(1); setCategory(e.target.value); }}><option value="">全部类别</option><option value="environment">环境变量数值</option><option value="nacos">Nacos 数值</option></select></label>
      <label className="text-xs text-[#bfc9e7]">审批状态<select className={`${control} mt-2 block`} value={status} onChange={e => { setRows([]); setLoading(true); setPage(1); setStatus(e.target.value); }}><option value="">全部状态</option>{Object.entries(labels).map(([value, text]) => <option value={value} key={value}>{text}</option>)}</select></label>
      <button className={control} onClick={() => { setLoading(true); setRevision(v => v+1); }}>刷新</button>
    </div>
    {notice ? <p role="status" className="text-sm text-emerald-300">{notice}</p> : null}
    {error ? <p role="alert" className="text-sm text-red-300">{error}</p> : null}
    <h2 className="text-lg font-bold">Key 查看审批 · {total} 条申请</h2>
    {loading ? <p className="text-sm text-[#bfc9e7]">正在加载...</p> : rows.length === 0 ? <p className="py-10 text-center text-[#bfc9e7]">暂无申请</p> : null}
    <div className="divide-y divide-white/10">{rows.map(row => <article className="min-w-0 space-y-3 py-5" key={row.id}>
      <div className="flex flex-wrap items-center justify-between gap-3"><h3 className="break-all text-sm font-bold">#{row.id} · {row.requester_name} · {row.category === "environment" ? "环境变量数值" : "Nacos 数值"}</h3><span className={`text-sm ${row.status === "pending" ? "text-yellow-300" : row.status === "approved" ? "text-emerald-300" : "text-[#bfc9e7]"}`}>{labels[row.status]}</span></div>
      <p className="break-all text-sm">环境：{row.environment_name} / {row.resource_name}</p>
      <p className="break-all font-mono text-xs text-[#bfc9e7]">{Object.entries(row.target).map(([key, value]) => `${key}: ${value}`).join(" · ")}</p>
      {row.reason ? <p className="break-all text-sm text-[#bfc9e7]">申请原因：{row.reason}</p> : null}
      <div className="flex flex-wrap gap-x-6 gap-y-2 text-xs text-[#bfc9e7]"><span>申请时间：{time(row.created_at)}</span><span>审批人：{row.reviewer_name ?? "-"}</span><span>审批时间：{time(row.reviewed_at)}</span><span>采集时间：{time(row.captured_at)}</span><span>有效期至：{time(row.expires_at)}</span></div>
      {row.review_note ? <p className="break-all text-sm text-[#bfc9e7]">审批备注：{row.review_note}</p> : null}
      {row.status === "pending" ? <button className={`${control} bg-[#0a1ae1]`} onClick={() => openReview(row)}>审批</button> : null}
    </article>)}</div>
    <div className="flex items-center justify-end gap-3 text-sm"><span>第 {page} 页</span><button className={control} disabled={page <= 1} onClick={() => { setRows([]); setLoading(true); setPage(page-1); }}>上一页</button><button className={control} disabled={page * 20 >= total} onClick={() => { setRows([]); setLoading(true); setPage(page+1); }}>下一页</button></div>
    <dialog ref={dialog} className="m-auto w-[min(580px,calc(100vw-32px))] rounded-[6px] border border-[#4b5fc6] bg-[#070b1b] p-6 text-white backdrop:bg-black/70">
      <form onSubmit={review} className="space-y-4">
        <h3 className="text-lg font-bold">审批申请 #{selected?.id}</h3>
        <p className="break-all text-sm text-[#bfc9e7]">{selected?.requester_name} · {selected?.environment_name} · {selected?.resource_name}</p>
        <p className="break-all font-mono text-xs text-[#bfc9e7]">{selected ? Object.entries(selected.target).map(([key, value]) => `${key}: ${value}`).join(" · ") : ""}</p>
        <div className="flex gap-6">{[["approved", "同意"], ["rejected", "拒绝"]].map(([value, text]) => <label className="flex items-center gap-2" key={value}><input type="radio" name="decision" value={value} checked={decision === value} onChange={() => setDecision(value)} />{text}</label>)}</div>
        {decision === "approved" ? <label className="block text-sm">有效期（分钟）<input className={`${control} mt-2 block w-full`} type="number" min={5} max={1440} required value={minutes} onChange={e => setMinutes(Number(e.target.value))} /></label> : null}
        <label className="block text-sm">审批备注<textarea className={`${control} mt-2 block min-h-24 w-full`} maxLength={1000} value={note} onChange={e => setNote(e.target.value)} /></label>
        {reviewError ? <p role="alert" className="text-sm text-red-300">{reviewError}</p> : null}
        <div className="flex justify-end gap-3"><button type="button" className={control} disabled={busy} onClick={() => dialog.current?.close()}>取消</button><button disabled={busy} className={`${control} bg-[#0a1ae1]`}>{busy ? "处理中..." : "确认审批"}</button></div>
      </form>
    </dialog>
  </section>;
}
