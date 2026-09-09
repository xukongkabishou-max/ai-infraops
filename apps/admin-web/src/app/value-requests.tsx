"use client";

import { Fragment, FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { ApprovalLink } from "./approval-link";

type Category = "environment" | "nacos";
export type NacosLine = { line_number: number; config_path: string; source_line: number; source_end_line: number };
type ReadApi = <T>(path: string, signal?: AbortSignal) => Promise<T>;
type WriteApi = <T>(path: string, method: "POST" | "PUT", body: Record<string, unknown>) => Promise<T>;
type RequestRecord = {
  id: number; category: Category; environment_name: string; resource_name: string;
  target: Record<string, string | number>; reason: string; status: string;
  created_at: string; reviewed_at: string | null; captured_at: string | null;
  expires_at: string | null; reviewer_name: string | null; review_note: string;
  requester_name: string; release_ticket?: string; release_version?: string;
  can_review?: boolean; can_view_value?: boolean;
};
type Snapshot = { snapshot: { value: string; pod_name?: string; container_name?: string; key?: string }; captured_at: string; expires_at: string; server_now: string };
const control = "min-h-9 rounded-[6px] border border-[#4b5fc6] px-3 py-2 text-xs font-bold text-[#c9d2f0] disabled:opacity-40";
const statusLabels: Record<string, string> = { pending: "待审批", approved: "已通过", rejected: "已拒绝", expired: "已过期", invalidated: "已失效，请重新申请" };
const errorMessage = (error: unknown, fallback: string) => error instanceof SyntaxError ? "审批服务暂时不可用，请稍后刷新重试" : error instanceof Error ? error.message : fallback;
const time = (value: string | null) => value ? new Date(value).toLocaleString("zh-CN", { hour12: false }) : "-";

function RecordFields({ items, className = "" }: { items: Array<[string, string | number | null | undefined]>; className?: string }) {
  return <dl className={`grid min-w-0 grid-cols-1 gap-x-8 gap-y-5 sm:grid-cols-2 ${className}`}>
    {items.map(([label, value]) => <div className="min-w-0" key={label}>
      <dt className="mb-1.5 text-xs text-[#bfc9e7]/55">{label}</dt>
      <dd className="break-words text-sm leading-6 text-[#e0e6f5] [overflow-wrap:anywhere]">{value === "" || value == null ? "-" : value}</dd>
    </div>)}
  </dl>;
}

export function ValueRequestButton({ target, label, mutate, selectableLines }: { target: Record<string, unknown>; label: string; mutate: WriteApi; selectableLines?: NacosLine[] }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [lineNumber, setLineNumber] = useState("");
  const [releaseTicket, setReleaseTicket] = useState("");
  const [releaseVersion, setReleaseVersion] = useState("");
  const [submittedId, setSubmittedId] = useState<number | null>(null);
  const isNacos = target.category === "nacos";
  const selection = selectableLines?.find(line => line.line_number === Number(lineNumber));
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy || (isNacos && !selection)) return;
    setBusy(true); setError("");
    try {
      const body = { ...target, release_ticket: releaseTicket, release_version: releaseVersion, ...(isNacos ? { line_number: Number(lineNumber) } : {}) };
      const result = await mutate<{ id: number }>("/api/value-requests", "POST", body);
      setMessage(`申请 #${result.id} 已提交，待管理员审批`);
      setSubmittedId(result.id);
      dialog.current?.close();
    } catch (e) { setError(errorMessage(e, "申请失败")); }
    finally { setBusy(false); }
  }
  return <div className="flex max-w-sm flex-wrap items-center justify-end gap-2 text-left">
    <button type="button" className={control} onClick={() => { setError(""); setLineNumber(""); dialog.current?.showModal(); }}>查看具体 Value</button>
    {message ? <span role="status" className="text-xs text-emerald-300">{message}</span> : null}
    {submittedId ? <ApprovalLink requestId={submittedId} /> : null}
    <dialog ref={dialog} className="m-auto w-[min(560px,calc(100vw-32px))] rounded-[6px] border border-[#4b5fc6] bg-[#070b1b] p-6 text-white backdrop:bg-black/70">
      <form onSubmit={submit} className="space-y-4">
        <h3 className="text-lg font-bold">申请查看 Value</h3>
        <p className="break-all text-sm text-[#c9d2f0]">{label}</p>
        {isNacos ? <div className="space-y-4">
          <label className="block text-sm">结构行号 <span className="text-red-300">*</span>
            <input required min={1} step={1} type="number" value={lineNumber} onChange={event => setLineNumber(event.target.value)} className="mt-2 h-11 w-full rounded-[6px] border border-white/20 bg-[#04050b] px-3" />
          </label>
          {selection ? <RecordFields items={[["对应配置路径", selection.config_path], ["原文行号", selection.source_line === selection.source_end_line ? selection.source_line : `${selection.source_line}–${selection.source_end_line}`]]} /> : lineNumber ? <p className="text-sm text-yellow-300">该行不对应独立配置值</p> : null}
        </div> : null}
        <p className="text-sm">是否确认提交申请？</p>
        <details className="text-sm text-[#c9d2f0]">
          <summary className="cursor-pointer">关联上线单（选填）</summary>
          <div className="mt-4 space-y-4">
            <label className="block">上线单号<input maxLength={200} value={releaseTicket} onChange={event => setReleaseTicket(event.target.value)} className="mt-2 h-10 w-full rounded-[6px] border border-white/20 bg-[#04050b] px-3" /></label>
            <label className="block">发布版本 / Commit ID<input maxLength={200} value={releaseVersion} onChange={event => setReleaseVersion(event.target.value)} className="mt-2 h-10 w-full rounded-[6px] border border-white/20 bg-[#04050b] px-3" /></label>
          </div>
        </details>
        {error ? <p role="alert" className="text-sm text-red-300">{error}</p> : null}
        <div className="flex justify-end gap-3"><button autoFocus type="button" className={control} onClick={() => dialog.current?.close()}>取消</button><button className={`${control} bg-[#0a1ae1]`} disabled={busy || (isNacos && !selection)}>{busy ? "提交中..." : "确认提交"}</button></div>
      </form>
    </dialog>
  </div>;
}

export function UserValueRequests({ category, read, requestId, mutate }: { category?: Category; read: ReadApi; requestId?: number; mutate?: WriteApi }) {
  const [rows, setRows] = useState<RequestRecord[]>([]);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [revision, setRevision] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [values, setValues] = useState<Record<number, Snapshot>>({});
  const [busy, setBusy] = useState<number | null>(null);
  const [expandedId, setExpandedId] = useState<number | null>(requestId ?? null);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [keyword, setKeyword] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [filters, setFilters] = useState({ from: "", to: "", keyword: "", status: "" });
  const generation = useRef(0);
  const invalidate = useCallback(() => { generation.current++; }, []);
  const reload = useCallback(() => { generation.current++; setValues({}); setLoading(true); setRevision(v => v + 1); }, []);
  function search(event: FormEvent) {
    event.preventDefault();
    if (from && to && from > to) { setError("开始日期不能晚于结束日期"); return; }
    setError(""); setPage(1); setExpandedId(null); setFilters({ from, to, keyword, status: statusFilter }); reload();
  }
  function toggle(rowId: number) {
    setExpandedId(current => current === rowId ? null : rowId);
    generation.current++; setValues({});
  }
  useEffect(() => {
    const controller = new AbortController();
    const query = new URLSearchParams({ category: category ?? "", page: String(page) });
    if (filters.from) query.set("date_from", filters.from);
    if (filters.to) query.set("date_to", filters.to);
    if (filters.keyword) query.set("keyword", filters.keyword);
    if (filters.status) query.set("status", filters.status);
    const path = requestId ? `/api/value-requests/${requestId}` : `/api/value-requests?${query}`;
    const load = () => read<{ items: RequestRecord[]; total: number; server_now: string }>(path, controller.signal)
      .then(data => { if (!controller.signal.aborted) { setRows(data.items); setTotal(data.total); setError(""); } })
      .catch(e => { if (!controller.signal.aborted) { setValues({}); setRows([]); setError(errorMessage(e, "加载失败")); } })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    void load();
    const interval = window.setInterval(load, 15000);
    return () => { controller.abort(); window.clearInterval(interval); invalidate(); };
  }, [category, page, revision, read, invalidate, requestId, filters]);
  async function reveal(row: RequestRecord) {
    const current = generation.current;
    setBusy(row.id); setError(""); setExpandedId(row.id);
    try {
      const data = await read<Snapshot>(`/api/value-requests/${row.id}/value`);
      if (current === generation.current) setValues(values => ({ ...values, [row.id]: data }));
    } catch (e) { if (current === generation.current) setError(errorMessage(e, "读取失败")); }
    finally { setBusy(null); }
  }
  return <section className="min-w-0 space-y-4 border-t border-white/10 pt-5">
    <div className="flex items-center justify-between gap-3"><h2 className="text-lg font-black">{requestId ? "审批详情" : category === "nacos" ? "Nacos 审批记录" : "环境变量审批记录"}</h2><button className={control} onClick={reload}>刷新</button></div>
    {!requestId ? <form onSubmit={search} className="flex flex-wrap items-end gap-3 text-xs text-[#bfc9e7]">
      <label>申请开始日期<input type="date" value={from} onChange={event => setFrom(event.target.value)} className={`${control} mt-1 block bg-[#04050b] [color-scheme:dark]`} /></label>
      <label>申请截止日期<input type="date" value={to} min={from || undefined} onChange={event => setTo(event.target.value)} className={`${control} mt-1 block bg-[#04050b] [color-scheme:dark]`} /></label>
      <label>状态<select value={statusFilter} onChange={event => setStatusFilter(event.target.value)} className={`${control} mt-1 block bg-[#04050b]`}><option value="">全部</option>{Object.entries(statusLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <label>关键词<input maxLength={200} value={keyword} onChange={event => setKeyword(event.target.value)} placeholder="Key、配置、环境或上线单" className={`${control} mt-1 block bg-[#04050b]`} /></label>
      <button className={`${control} bg-[#0a1ae1]`}>查询</button>
      <button type="button" className={control} onClick={() => { setFrom(""); setTo(""); setKeyword(""); setStatusFilter(""); setFilters({ from:"",to:"",keyword:"",status:"" }); setPage(1); setExpandedId(null); reload(); }}>重置</button>
    </form> : null}
    {error ? <p role="alert" className="text-sm text-red-300">{error}</p> : null}
    {loading ? <p className="text-sm text-[#bfc9e7]">正在加载...</p> : rows.length === 0 && !error ? <p className="py-10 text-center text-[#bfc9e7]">暂无申请记录</p> : null}
    <div className="overflow-x-auto [color-scheme:dark]"><table className="w-full min-w-[820px] table-fixed text-left text-sm">
      <thead className="border-y border-white/15 bg-white/[0.025] text-xs text-[#bfc9e7]/65"><tr>
        <th className="w-16 px-3 py-3">编号</th><th className="px-3 py-3">申请内容</th><th className="w-40 px-3 py-3">环境</th><th className="w-28 px-3 py-3">状态</th><th className="w-40 px-3 py-3">申请时间</th><th className="w-36 px-3 py-3">操作</th>
      </tr></thead><tbody>
      {rows.map(row => {
        const status = row.status;
        const approved = status === "approved" || status === "expired";
        const snapshot = approved ? values[row.id] : undefined;
        const expanded = expandedId === row.id;
        return <Fragment key={row.id}>
          <tr className="border-b border-white/10 align-top hover:bg-white/[0.025]">
            <td className="px-3 py-3 text-xs text-[#bfc9e7]/65">#{row.id}</td>
            <td className="px-3 py-3"><button className="block max-w-full truncate text-left font-mono text-sm text-[#a9baff]" title={String(row.target.key ?? row.target.data_id)} onClick={() => toggle(row.id)}>{row.target.key ?? row.target.data_id}</button><p className="mt-1 truncate text-xs text-[#bfc9e7]/55">{row.category === "nacos" ? `Nacos · ${row.target.config_path ?? row.target.group}` : `${row.target.namespace} / ${row.target.workload}`}</p></td>
            <td className="break-words px-3 py-3 text-xs leading-5 text-[#bfc9e7]">{row.environment_name}</td>
            <td className={`px-3 py-3 text-xs ${status === "pending" ? "text-yellow-300" : approved ? "text-emerald-300" : "text-[#bfc9e7]"}`}>{statusLabels[status] ?? status}</td>
            <td className="px-3 py-3 text-xs leading-5 text-[#bfc9e7]">{time(row.created_at)}</td>
            <td className="px-3 py-3"><div className="flex flex-wrap gap-3 text-xs text-[#9fb0ff]"><button aria-expanded={expanded} onClick={() => toggle(row.id)}>{expanded ? "收起" : "展开"}</button>{approved && row.can_view_value !== false ? <button disabled={busy !== null} onClick={() => reveal(row)}>{busy === row.id ? "读取中..." : "查看快照"}</button> : null}</div></td>
          </tr>
          {expanded ? <tr className="border-b border-white/15"><td colSpan={6} className="bg-[#070b1b] px-5 py-4"><article className="min-w-0 space-y-4">
          <header className="flex flex-wrap items-start justify-between gap-4">
            <div className="min-w-0 flex-1 basis-56">
              <p className="mb-2 text-xs text-[#bfc9e7]/60">申请 #{row.id} <span className="mx-2 text-white/20">/</span> {row.category === "environment" ? "环境变量数值" : "Nacos 配置"}</p>
              <h3 className="break-words font-mono text-base font-bold leading-7 text-white [overflow-wrap:anywhere]">{row.target.key ?? row.target.data_id}</h3>
            </div>
            <span className={`shrink-0 rounded-[5px] border px-3 py-1.5 text-xs font-bold ${status === "approved" ? "border-emerald-400/25 bg-emerald-400/10 text-emerald-300" : status === "pending" ? "border-yellow-400/25 bg-yellow-400/10 text-yellow-300" : "border-white/15 bg-white/5 text-[#bfc9e7]"}`}>{statusLabels[status] ?? status}</span>
          </header>
          <ApprovalLink requestId={row.id} />
          <RecordFields className="xl:grid-cols-3" items={[
            ["申请人", row.requester_name],
            ["所属环境", row.environment_name],
            [row.category === "environment" ? "主机" : "Nacos 实例", row.resource_name],
            ["Namespace", row.category === "environment" ? row.target.namespace : row.target.namespace_id || "public"],
            ...(row.category === "environment" ? [["工作负载", `${row.target.kind} / ${row.target.workload}`], ["容器", row.target.container]] as Array<[string, string | number]> : [["Group", row.target.group]] as Array<[string, string | number]>),
            ["审批人", row.reviewer_name],
            ...(row.category === "nacos" && row.target.line_number ? [["结构行号", row.target.line_number], ["配置路径", row.target.config_path], ["原文行号", row.target.source_line === row.target.source_end_line ? row.target.source_line : `${row.target.source_line}-${row.target.source_end_line}`]] as Array<[string, string | number]> : []),
          ]} />
          {row.release_ticket || row.release_version ? <RecordFields items={[["上线单号", row.release_ticket], ["发布版本 / Commit ID", row.release_version]]} /> : null}
          <div className="border-y border-white/10 bg-white/[0.025] px-4 py-5 sm:px-5">
            <RecordFields className="xl:grid-cols-4" items={[["申请时间", time(row.created_at)], ["审批时间", time(row.reviewed_at)], ["数值采集时间", time(row.captured_at)], ["原授权截止时间", time(row.expires_at)]]} />
          </div>
          {row.reason || row.review_note ? <RecordFields items={[
            ...(row.reason ? [["申请原因", row.reason]] as Array<[string, string]> : []),
            ...(row.review_note ? [["审批备注", row.review_note]] as Array<[string, string]> : []),
          ]} /> : null}
          {row.can_review && mutate ? <DetailReview requestId={row.id} mutate={mutate} onReviewed={reload} /> : null}
          {approved && row.can_view_value !== false ? <div className="flex flex-wrap items-center justify-between gap-3">
            <h4 className="text-sm font-bold text-[#e0e6f5]">审批时的历史快照</h4>
            <button className={control} disabled={busy !== null} onClick={() => snapshot ? setValues(current => { const next = { ...current }; delete next[row.id]; return next; }) : reveal(row)}>{busy === row.id ? "读取中..." : snapshot ? "隐藏快照" : "查看历史快照"}</button>
          </div> : null}
          {snapshot ? <div className="min-w-0 space-y-4 border-l-2 border-emerald-400 pl-4 sm:pl-5">
            <RecordFields className="xl:grid-cols-3" items={[
              ["快照采集时间", time(snapshot.captured_at)],
              ...(snapshot.snapshot.pod_name ? [["来源 Pod", snapshot.snapshot.pod_name], ["来源容器", snapshot.snapshot.container_name]] as Array<[string, string | undefined]> : []),
            ]} />
            <pre className="max-h-[520px] overflow-auto whitespace-pre-wrap break-words bg-[#04050b] px-5 py-4 font-mono text-sm leading-7 text-[#e0f2e9] [overflow-wrap:anywhere]">{snapshot.snapshot.value === "" ? "（空字符串）" : snapshot.snapshot.value}</pre>
          </div> : null}
        </article></td></tr> : null}</Fragment>;
      })}
    </tbody></table></div>
    {!requestId ? <div className="flex items-center justify-end gap-3 text-xs"><span>共 {total} 条 · 第 {page} 页</span><button className={control} disabled={page <= 1} onClick={() => { reload(); setPage(page-1); }}>上一页</button><button className={control} disabled={page * 20 >= total} onClick={() => { reload(); setPage(page+1); }}>下一页</button></div> : null}
  </section>;
}

function DetailReview({ requestId, mutate, onReviewed }: { requestId: number; mutate: WriteApi; onReviewed: () => void }) {
  const [decision, setDecision] = useState("approved");
  const [minutes, setMinutes] = useState(60);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function review(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true); setError("");
    try {
      await mutate(`/api/value-requests/${requestId}/review`, "POST", { decision, note, validity_minutes: decision === "approved" ? minutes : 60 });
      onReviewed();
    } catch (e) { setError(errorMessage(e, "审批失败")); }
    finally { setBusy(false); }
  }
  return <form onSubmit={review} className="space-y-5 border-t border-white/10 pt-5">
    <h3 className="text-base font-bold">处理申请</h3>
    <div className="flex gap-6">{[["approved", "同意"], ["rejected", "拒绝"]].map(([value, label]) => <label key={value} className="flex items-center gap-2 text-sm"><input type="radio" name={`decision-${requestId}`} checked={decision === value} onChange={() => setDecision(value)} />{label}</label>)}</div>
    <div className="grid gap-5 sm:grid-cols-2">
      {decision === "approved" ? <label className="block text-sm">有效期（分钟）<input type="number" min={5} max={1440} required value={minutes} onChange={event => setMinutes(Number(event.target.value))} className="mt-2 h-11 w-full rounded-[6px] border border-white/20 bg-[#04050b] px-3" /></label> : null}
      <label className="block text-sm">审批备注<textarea maxLength={1000} value={note} onChange={event => setNote(event.target.value)} className="mt-2 min-h-20 w-full rounded-[6px] border border-white/20 bg-[#04050b] p-3" /></label>
    </div>
    {error ? <p role="alert" className="text-sm text-red-300">{error}</p> : null}
    <button className={`${control} bg-[#0a1ae1]`} disabled={busy}>{busy ? "处理中..." : "确认审批"}</button>
  </form>;
}
