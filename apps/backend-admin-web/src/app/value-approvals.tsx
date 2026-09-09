"use client";

import { Fragment, FormEvent, useEffect, useRef, useState } from "react";
import { ApprovalLink } from "./approval-link";

type NacosSelection = { line_number: number; config_path: string; source_line: number; source_end_line: number };
type ValueSnapshot = { snapshot: { value?: string; values?: Array<NacosSelection & { value: string }> }; captured_at: string };

type Approval = {
  id: number; requester_name: string; requester_id: number; category: string;
  environment_name: string; resource_name: string; target: Record<string, unknown> & { selections?: NacosSelection[] };
  reason: string; status: string; created_at: string; reviewed_at: string | null;
  captured_at: string | null; expires_at: string | null; reviewer_name: string | null; review_note: string;
  release_ticket?: string; release_version?: string;
};
const control = "min-h-10 rounded-[6px] border border-[#4b5fc6] bg-[#070b1b] px-3 py-2 text-sm text-[#c9d2f0] disabled:opacity-40";
const time = (value: string | null) => value ? new Date(value).toLocaleString("zh-CN", { hour12: false }) : "-";
const labels: Record<string, string> = { pending: "待审批", approved: "已通过", rejected: "已拒绝", expired: "已过期", invalidated: "已失效" };
const errorMessage = (error: unknown, fallback: string) => error instanceof SyntaxError ? "审批服务暂时不可用，请稍后刷新重试" : error instanceof Error ? error.message : fallback;

function ApprovalFields({ items, className = "" }: { items: Array<[string, unknown]>; className?: string }) {
  return <dl className={`grid min-w-0 grid-cols-1 gap-x-8 gap-y-5 sm:grid-cols-2 ${className}`}>
    {items.map(([label, value]) => <div className="min-w-0" key={label}>
      <dt className="mb-1.5 text-xs text-[#bfc9e7]/55">{label}</dt>
      <dd className="break-words text-sm leading-6 text-[#e0e6f5] [overflow-wrap:anywhere]">{value === "" || value == null ? "-" : String(value)}</dd>
    </div>)}
  </dl>;
}

function targetFields(row: Approval): Array<[string, unknown]> {
  return [
    ["所属环境", row.environment_name],
    [row.category === "environment" ? "主机" : "Nacos 实例", row.resource_name],
    ["Namespace", row.category === "environment" ? row.target.namespace : row.target.namespace_id || "public"],
    ...(row.category === "environment" ? [["工作负载", `${row.target.kind} / ${row.target.workload}`], ["容器", row.target.container]] as Array<[string, unknown]> : [["Group", row.target.group]] as Array<[string, unknown]>),
    ...(row.category === "nacos" && row.target.line_number ? [["结构行号", row.target.line_number], ["配置路径", row.target.config_path], ["原文行号", row.target.source_line === row.target.source_end_line ? row.target.source_line : `${row.target.source_line}-${row.target.source_end_line}`]] as Array<[string, unknown]> : []),
    ...(row.target.line_ranges ? [["申请页面行号", row.target.line_ranges], ["配置值数量", row.target.selections?.length], ["配置路径", row.target.selections?.map(item => `第 ${item.line_number} 行：${item.config_path}（原文 ${item.source_line}-${item.source_end_line} 行）`).join("；")]] as Array<[string, unknown]> : []),
  ];
}

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
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [keyword, setKeyword] = useState("");
  const [filters, setFilters] = useState({ from:"", to:"", keyword:"" });
  const [snapshots, setSnapshots] = useState<Record<number, ValueSnapshot>>({});
  const [reading, setReading] = useState<number | null>(null);
  const snapshotGeneration = useRef(0);
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const schedule = () => {
      if (!controller.signal.aborted) timer = setTimeout(() => { if (document.hidden) schedule(); else void load(); }, 15000);
    };
    const query = new URLSearchParams({ page: String(page) });
    if (category) query.set("category", category);
    if (status) query.set("status", status);
    if (filters.from) query.set("date_from", filters.from);
    if (filters.to) query.set("date_to", filters.to);
    if (filters.keyword) query.set("keyword", filters.keyword);
    const load = async () => {
      try {
        const response = await fetch(`${apiBaseUrl}/api/admin/value-requests?${query}`, { headers: { Authorization: `Bearer ${accessToken}` }, cache: "no-store", signal: controller.signal });
        const data = await response.json();
        if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "加载失败");
        if (!controller.signal.aborted) { setRows(data.items); setTotal(data.total); setError(""); }
      } catch (e) { if (!controller.signal.aborted) { setSnapshots({}); setRows([]); setError(errorMessage(e, "加载失败")); } }
      finally { if (!controller.signal.aborted) { setLoading(false); schedule(); } }
    };
    void load();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [accessToken, apiBaseUrl, category, status, page, revision, filters]);
  function clearSnapshots() { snapshotGeneration.current++; setSnapshots({}); setExpandedId(null); }
  function search(event: FormEvent) {
    event.preventDefault();
    if (from && to && from > to) { setError("开始日期不能晚于结束日期"); return; }
    clearSnapshots(); setPage(1); setLoading(true); setFilters({ from, to, keyword }); setRevision(value => value+1);
  }
  async function readSnapshot(row: Approval) {
    const generation = snapshotGeneration.current;
    setReading(row.id); setError(""); setExpandedId(row.id);
    try {
      const response = await fetch(`${apiBaseUrl}/api/admin/value-requests/${row.id}/value`, { headers: { Authorization: `Bearer ${accessToken}` }, cache: "no-store" });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "快照读取失败");
      if (generation === snapshotGeneration.current) setSnapshots(current => ({ ...current, [row.id]: data }));
    } catch (e) { if (generation === snapshotGeneration.current) setError(errorMessage(e, "快照读取失败")); }
    finally { setReading(null); }
  }
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
    } catch (e) { setReviewError(errorMessage(e, "审批失败")); }
    finally { setBusy(false); }
  }
  return <section className="min-w-0 space-y-5">
    <div className="flex flex-wrap items-end gap-4">
      <label className="text-xs text-[#bfc9e7]">申请类别<select className={`${control} mt-2 block`} value={category} onChange={e => { clearSnapshots(); setRows([]); setLoading(true); setPage(1); setCategory(e.target.value); }}><option value="">全部类别</option><option value="environment">环境变量数值</option><option value="nacos">Nacos 数值</option></select></label>
      <label className="text-xs text-[#bfc9e7]">审批状态<select className={`${control} mt-2 block`} value={status} onChange={e => { clearSnapshots(); setRows([]); setLoading(true); setPage(1); setStatus(e.target.value); }}><option value="">全部状态</option>{Object.entries(labels).map(([value, text]) => <option value={value} key={value}>{text}</option>)}</select></label>
      <button className={control} disabled={loading} onClick={() => { clearSnapshots(); setLoading(true); setRevision(v => v+1); }}>刷新</button>
    </div>
    <form onSubmit={search} className="flex flex-wrap items-end gap-3 text-xs text-[#bfc9e7]">
      <label>申请开始日期<input type="date" value={from} onChange={event => setFrom(event.target.value)} className={`${control} mt-1 block [color-scheme:dark]`} /></label>
      <label>申请截止日期<input type="date" value={to} min={from || undefined} onChange={event => setTo(event.target.value)} className={`${control} mt-1 block [color-scheme:dark]`} /></label>
      <label>关键词<input maxLength={200} value={keyword} onChange={event => setKeyword(event.target.value)} placeholder="申请人、Key、环境或上线单" className={`${control} mt-1 block`} /></label>
      <button className={`${control} bg-[#0a1ae1]`}>查询</button>
      <button type="button" className={control} onClick={() => { clearSnapshots(); setFrom(""); setTo(""); setKeyword(""); setCategory(""); setStatus(""); setFilters({from:"",to:"",keyword:""}); setPage(1); setLoading(true); setRevision(value=>value+1); }}>重置</button>
    </form>
    {notice ? <p role="status" className="text-sm text-emerald-300">{notice}</p> : null}
    {error ? <p role="alert" className="text-sm text-red-300">{error}</p> : null}
    <h2 className="text-lg font-bold">Key 查看审批 · {total} 条申请</h2>
    {loading ? <p className="text-sm text-[#bfc9e7]">正在加载...</p> : rows.length === 0 && !error ? <p className="py-10 text-center text-[#bfc9e7]">暂无申请</p> : null}
    <div className="overflow-x-auto [color-scheme:dark]"><table className="w-full min-w-[900px] table-fixed text-left text-sm">
      <thead className="border-y border-white/15 bg-white/[0.025] text-xs text-[#bfc9e7]/65"><tr>
        <th className="w-16 px-3 py-3">编号</th><th className="px-3 py-3">申请内容</th><th className="w-28 px-3 py-3">申请人</th><th className="w-36 px-3 py-3">环境</th><th className="w-24 px-3 py-3">状态</th><th className="w-40 px-3 py-3">申请时间</th><th className="w-40 px-3 py-3">操作</th>
      </tr></thead><tbody>{rows.map(row => <Fragment key={row.id}>
        <tr className="border-b border-white/10 align-top hover:bg-white/[0.025]">
          <td className="px-3 py-3 text-xs text-[#bfc9e7]/65">#{row.id}</td>
          <td className="px-3 py-3"><button className="block max-w-full truncate text-left font-mono text-sm text-[#a9baff]" title={String(row.target.key ?? row.target.data_id)} onClick={() => { snapshotGeneration.current++; setSnapshots({}); setExpandedId(current => current===row.id ? null : row.id); }}>{String(row.target.key ?? row.target.data_id ?? "-")}</button><p className="mt-1 truncate text-xs text-[#bfc9e7]/55">{row.category === "nacos" ? `Nacos · ${row.target.config_path ?? row.target.group}` : `${row.target.namespace} / ${row.target.workload}`}</p></td>
          <td className="break-words px-3 py-3 text-xs text-[#bfc9e7]">{row.requester_name}</td>
          <td className="break-words px-3 py-3 text-xs leading-5 text-[#bfc9e7]">{row.environment_name}</td>
          <td className={`px-3 py-3 text-xs ${row.status === "pending" ? "text-yellow-300" : ["approved","expired"].includes(row.status) ? "text-emerald-300" : "text-[#bfc9e7]"}`}>{labels[row.status]}</td>
          <td className="px-3 py-3 text-xs leading-5 text-[#bfc9e7]">{time(row.created_at)}</td>
          <td className="px-3 py-3"><div className="flex flex-wrap gap-3 text-xs text-[#9fb0ff]">
            <button aria-expanded={expandedId===row.id} onClick={() => { snapshotGeneration.current++; setSnapshots({}); setExpandedId(current => current===row.id ? null : row.id); }}>{expandedId===row.id ? "收起" : "展开"}</button>
            {row.status === "pending" ? <button onClick={() => openReview(row)}>审批</button> : null}
            {["approved","expired"].includes(row.status) ? <button disabled={reading!==null} onClick={() => readSnapshot(row)}>{reading===row.id ? "读取中..." : "查看快照"}</button> : null}
          </div></td>
        </tr>
        {expandedId===row.id ? <tr className="border-b border-white/15"><td colSpan={7} className="bg-[#070b1b] px-5 py-4"><article className="min-w-0 space-y-4">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 flex-1 basis-56">
          <p className="mb-2 text-xs text-[#bfc9e7]/60">申请 #{row.id} <span className="mx-2 text-white/20">/</span> {row.category === "environment" ? "环境变量数值" : "Nacos 配置"}</p>
          <h3 className="break-words font-mono text-base font-bold leading-7 text-white [overflow-wrap:anywhere]">{String(row.target.key ?? row.target.data_id ?? "-")}</h3>
        </div>
        <div className="flex shrink-0 items-center gap-3">
          <span className={`rounded-[5px] border px-3 py-1.5 text-xs font-bold ${row.status === "pending" ? "border-yellow-400/25 bg-yellow-400/10 text-yellow-300" : row.status === "approved" ? "border-emerald-400/25 bg-emerald-400/10 text-emerald-300" : "border-white/15 bg-white/5 text-[#bfc9e7]"}`}>{labels[row.status]}</span>
          {row.status === "pending" ? <button className={`${control} bg-[#0a1ae1]`} onClick={() => openReview(row)}>审批</button> : null}
        </div>
      </header>
      <ApprovalLink requestId={row.id} />
      <div className="grid min-w-0 gap-6 xl:grid-cols-[minmax(0,3fr)_minmax(0,1fr)]">
        <ApprovalFields className="xl:grid-cols-3" items={targetFields(row)} />
        <ApprovalFields className="border-t border-white/10 pt-5 xl:grid-cols-1 xl:border-t-0 xl:border-l xl:pt-0 xl:pl-6" items={[["申请人", row.requester_name], ["审批人", row.reviewer_name]]} />
      </div>
      {row.release_ticket || row.release_version ? <ApprovalFields items={[["上线单号", row.release_ticket], ["发布版本 / Commit ID", row.release_version]]} /> : null}
      <div className="border-y border-white/10 bg-white/[0.025] px-4 py-5 sm:px-5">
        <ApprovalFields className="xl:grid-cols-4" items={[["申请时间", time(row.created_at)], ["审批时间", time(row.reviewed_at)], ["数值采集时间", time(row.captured_at)], ["原授权截止时间", time(row.expires_at)]]} />
      </div>
      {row.reason || row.review_note ? <ApprovalFields items={[
        ...(row.reason ? [["申请原因", row.reason]] as Array<[string, unknown]> : []),
        ...(row.review_note ? [["审批备注", row.review_note]] as Array<[string, unknown]> : []),
      ]} /> : null}
      {snapshots[row.id] ? <div className="min-w-0 space-y-3 border-l-2 border-emerald-400 pl-4">
        <div className="flex items-center justify-between gap-3"><h3 className="text-sm font-bold">审批时的历史快照</h3><button className="text-xs text-[#9fb0ff]" onClick={() => setSnapshots(current => { const next={...current}; delete next[row.id]; return next; })}>隐藏快照</button></div>
        <p className="text-xs text-emerald-300">采集时间：{time(snapshots[row.id].captured_at)}</p>
        <div className="max-h-[520px] overflow-auto">{snapshots[row.id].snapshot.values ? snapshots[row.id].snapshot.values!.map(item => <div key={item.line_number} className="border-b border-white/10 py-3"><p className="mb-2 break-all text-xs text-[#c9d2f0]">页面第 {item.line_number} 行 · {item.config_path} · 原文 {item.source_line}-{item.source_end_line} 行</p><pre className="whitespace-pre-wrap break-words bg-[#04050b] p-4 font-mono text-sm leading-7 [overflow-wrap:anywhere]">{item.value === "" ? "（空字符串）" : item.value}</pre></div>) : <pre className="whitespace-pre-wrap break-words bg-[#04050b] p-4 font-mono text-sm leading-7 [overflow-wrap:anywhere]">{snapshots[row.id].snapshot.value === "" ? "（空字符串）" : snapshots[row.id].snapshot.value}</pre>}</div>
      </div> : null}
    </article></td></tr> : null}</Fragment>)}</tbody></table></div>
    <div className="flex items-center justify-end gap-3 text-sm"><span>第 {page} 页</span><button className={control} disabled={page <= 1} onClick={() => { clearSnapshots(); setRows([]); setLoading(true); setPage(page-1); }}>上一页</button><button className={control} disabled={page * 20 >= total} onClick={() => { clearSnapshots(); setRows([]); setLoading(true); setPage(page+1); }}>下一页</button></div>
    <dialog ref={dialog} className="m-auto w-[min(580px,calc(100vw-32px))] rounded-[6px] border border-[#4b5fc6] bg-[#070b1b] p-6 text-white backdrop:bg-black/70">
      <form onSubmit={review} className="space-y-4">
        <h3 className="text-lg font-bold">审批申请 #{selected?.id}</h3>
        {selected ? <div className="space-y-5 border-y border-white/10 py-5">
          <p className="break-words font-mono text-sm font-bold leading-6 [overflow-wrap:anywhere]">{String(selected.target.key ?? selected.target.data_id ?? "-")}</p>
          <ApprovalFields items={[["申请人", selected.requester_name], ...targetFields(selected)]} />
        </div> : null}
        <div className="flex gap-6">{[["approved", "同意"], ["rejected", "拒绝"]].map(([value, text]) => <label className="flex items-center gap-2" key={value}><input type="radio" name="decision" value={value} checked={decision === value} onChange={() => setDecision(value)} />{text}</label>)}</div>
        {decision === "approved" ? <label className="block text-sm">有效期（分钟）<input className={`${control} mt-2 block w-full`} type="number" min={5} max={1440} required value={minutes} onChange={e => setMinutes(Number(e.target.value))} /></label> : null}
        <label className="block text-sm">审批备注<textarea className={`${control} mt-2 block min-h-24 w-full`} maxLength={1000} value={note} onChange={e => setNote(e.target.value)} /></label>
        {reviewError ? <p role="alert" className="text-sm text-red-300">{reviewError}</p> : null}
        <div className="flex justify-end gap-3"><button type="button" className={control} disabled={busy} onClick={() => dialog.current?.close()}>取消</button><button disabled={busy} className={`${control} bg-[#0a1ae1]`}>{busy ? "处理中..." : "确认审批"}</button></div>
      </form>
    </dialog>
  </section>;
}
