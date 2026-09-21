"use client";

import { FormEvent, useEffect, useRef, useState } from "react";

type RedisInstance = {
  id: number;
  environment_name: string;
  instance_name: string;
  base_url: string;
  status: string;
  deployment_mode: "standalone" | "cluster";
  database_count: number;
  endpoints: Array<{ host: string; port: number }>;
  databases: number[];
  last_error?: string | null;
};
type RedisKeySummary = { key: string; type: string; ttl: number; persistent: boolean };
type RedisKeyDetail = RedisKeySummary & { length: number; truncated: boolean; value: unknown };
const control = "min-h-10 rounded-[6px] border border-[#344375] bg-[#070b1b] px-3 py-2 text-sm text-[#dce4f6] disabled:opacity-40";
const time = (value: string | null) => value ? new Date(value).toLocaleString("zh-CN", { hour12: false }) : "-";
const MAX_RESULT_KEYS = 2000;
const PAGE_SIZE = 100;

function accessToken(): string | null {
  try {
    const raw = window.sessionStorage.getItem("ai-infraops:user-web-session");
    const parsed = raw ? JSON.parse(raw) : null;
    return parsed?.access_token ?? null;
  } catch {
    return null;
  }
}

export function RedisBrowser({ apiBaseUrl }: { apiBaseUrl: string }) {
  const [instances, setInstances] = useState<RedisInstance[]>([]);
  const [instanceId, setInstanceId] = useState("");
  const [db, setDb] = useState(0);
  const [pattern, setPattern] = useState("*");
  const [cursor, setCursor] = useState(0);
  const [keys, setKeys] = useState<RedisKeySummary[]>([]);
  const [limitReached, setLimitReached] = useState(false);
  const [detail, setDetail] = useState<RedisKeyDetail | null>(null);
  const [selectedKey, setSelectedKey] = useState("");
  const [keyType, setKeyType] = useState("string");
  const [valueText, setValueText] = useState("");
  const [ttl, setTtl] = useState("3600");
  const [files, setFiles] = useState<File[]>([]);
  const [prefix, setPrefix] = useState("import");
  const [overwrite, setOverwrite] = useState(false);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const generation = useRef(0);
  const instance = instances.find(item => String(item.id) === instanceId);

  async function api<T>(path: string, init?: RequestInit): Promise<T> {
    const response = await fetch(`${apiBaseUrl}/api/redis${path}`, {
      cache: "no-store",
      headers: { Authorization: `Bearer ${accessToken()}`, ...(init?.body instanceof FormData ? {} : { "Content-Type": "application/json" }) },
      ...init,
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Redis 操作失败");
    return data;
  }
  useEffect(() => {
    const controller = new AbortController();
    fetch(`${apiBaseUrl}/api/redis/instances`, { signal: controller.signal, cache: "no-store", headers: { Authorization: `Bearer ${accessToken()}` } })
      .then(async response => {
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail ?? "Redis 实例加载失败");
        setInstances(data);
        setInstanceId(current => current || (data[0] ? String(data[0].id) : ""));
      })
      .catch(error => { if (error.name !== "AbortError") setError(error.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [apiBaseUrl]);

  function changeInstance(value: string) {
    const next = instances.find(item => String(item.id) === value);
    setInstanceId(value); setDb(next?.databases[0] ?? 0); setKeys([]); setCursor(0); setDetail(null); setError(""); setNotice("");
  }
  async function scan(nextCursor = 0, append = false) {
    if (!instanceId) return;
    const current = ++generation.current; setLoading(true); setError("");
    try {
      const query = new URLSearchParams({ db: String(db), cursor: String(nextCursor), pattern, count: String(PAGE_SIZE) });
      const data = await api<{ items: RedisKeySummary[]; cursor: number; completed: boolean }>(`/instances/${instanceId}/keys?${query}`);
      if (current !== generation.current) return;
      const base = append ? keys : [];
      const remaining = Math.max(0, MAX_RESULT_KEYS - base.length);
      const nextItems = data.items.slice(0, remaining);
      setKeys([...base, ...nextItems]);
      setLimitReached(base.length + nextItems.length >= MAX_RESULT_KEYS);
      setCursor(data.cursor);
    } catch (error) { if (current === generation.current) setError(error instanceof Error ? error.message : "查询失败"); }
    finally { if (current === generation.current) setLoading(false); }
  }
  async function refreshStatus() {
    if (!instanceId) return;
    setBusy(true); setError(""); setNotice("");
    try {
      const data = await api<{ checked_at: string }>(`/instances/${instanceId}/refresh`, { method: "POST" });
      setNotice(`连接状态已刷新：${time(data.checked_at)}`);
      const rows = await api<RedisInstance[]>("/instances");
      setInstances(rows);
    } catch (error) { setError(error instanceof Error ? error.message : "状态刷新失败"); }
    finally { setBusy(false); }
  }
  async function openKey(key: string) {
    setBusy(true); setError("");
    try {
      const data = await api<RedisKeyDetail>(`/instances/${instanceId}/key?db=${db}&key=${encodeURIComponent(key)}`);
      setDetail(data); setSelectedKey(key); setKeyType(data.type); setValueText(typeof data.value === "string" ? data.value : JSON.stringify(data.value, null, 2)); setTtl(String(data.persistent ? 0 : data.ttl));
    } catch (error) { setError(error instanceof Error ? error.message : "读取失败"); }
    finally { setBusy(false); }
  }
  async function saveKey(event: FormEvent) {
    event.preventDefault(); if (!instanceId) return;
    setBusy(true); setError(""); setNotice("");
    try {
      const parsed = keyType === "string" ? valueText : JSON.parse(valueText);
      await api(`/instances/${instanceId}/key`, { method: "PUT", body: JSON.stringify({ key: selectedKey, db, type: keyType, value: parsed, ttl_seconds: Number(ttl) }) });
      setNotice(`Key ${selectedKey} 已保存`); await scan(0, false);
    } catch (error) { setError(error instanceof Error ? error.message : "保存失败"); }
    finally { setBusy(false); }
  }
  async function deleteKey() {
    if (!selectedKey || !window.confirm(`确认删除 ${selectedKey}？`)) return;
    setBusy(true); setError("");
    try {
      await api(`/instances/${instanceId}/key?db=${db}&key=${encodeURIComponent(selectedKey)}`, { method: "DELETE" });
      setDetail(null); setSelectedKey(""); setNotice("Key 已删除"); await scan(0, false);
    } catch (error) { setError(error instanceof Error ? error.message : "删除失败"); }
    finally { setBusy(false); }
  }
  async function uploadFiles(event: FormEvent) {
    event.preventDefault(); if (!instanceId || !files.length) return;
    setBusy(true); setError(""); setNotice("");
    try {
      const form = new FormData();
      files.slice(0, 3).forEach(file => form.append("files", file));
      const data = await api<{ status: string; files: Array<{ filename: string; status: string; error?: string }> }>(
        `/instances/${instanceId}/files?db=${db}&key_prefix=${encodeURIComponent(prefix)}&overwrite=${overwrite}`,
        { method: "POST", body: form },
      );
      setNotice(`导入${data.status === "succeeded" ? "成功" : data.status === "partial" ? "部分成功" : "失败"}`);
      await scan(0, false);
    } catch (error) { setError(error instanceof Error ? error.message : "文件导入失败"); }
    finally { setBusy(false); }
  }
  return <section className="min-w-0 space-y-4">
    <div className="flex flex-wrap items-center gap-3"><h2 className="mr-auto text-lg font-bold">Redis 数据浏览</h2><button type="button" className={control} disabled={!instanceId || busy} onClick={refreshStatus}>刷新状态</button></div>
    <div className="grid gap-3 rounded-[6px] border border-white/10 bg-[#04050b]/60 p-4 md:grid-cols-2 xl:grid-cols-4">
      <label className="text-sm">环境 / 实例<select className={control + " mt-2 w-full"} value={instanceId} onChange={event => changeInstance(event.target.value)}>{instances.map(item => <option key={item.id} value={item.id}>{item.environment_name} / {item.instance_name}</option>)}</select></label>
      <label className="text-sm">DB<select className={control + " mt-2 w-full"} disabled={instance?.deployment_mode === "cluster"} value={db} onChange={event => setDb(Number(event.target.value))}>{instance?.databases.map(item => <option key={item} value={item}>DB {item}</option>)}</select></label>
      <label className="text-sm">匹配模式<input className={control + " mt-2 w-full font-mono"} value={pattern} onChange={event => setPattern(event.target.value)} /></label>
      <div className="flex items-end gap-2"><button type="button" className={control + " bg-[#0a1ae1]"} disabled={!instanceId || loading} onClick={() => scan(0, false)}>{loading ? "查询中..." : "查询 Key"}</button>{cursor > 0 && !limitReached ? <button type="button" className={control} disabled={loading} onClick={() => scan(cursor, true)}>加载更多</button> : null}</div>
    </div>
    {instance ? <p className="break-all text-xs text-[#bfc9e7]/60">{instance.environment_name} · {instance.deployment_mode} · {instance.endpoints.map(item => `${item.host}:${item.port}`).join(", ")}</p> : null}
    {error ? <p role="alert" className="text-sm text-red-300">{error}</p> : null}
    {notice ? <p role="status" className="text-sm text-emerald-300">{notice}</p> : null}
    <div className="grid min-w-0 gap-4 xl:grid-cols-[380px_1fr]">
      <div className="max-h-[640px] overflow-auto border-y border-white/10"><div className={`sticky top-0 px-3 py-2 text-xs ${limitReached ? "bg-[#4a1a05] text-yellow-200" : "bg-[#070b1b] text-[#bfc9e7]/60"}`}>{limitReached ? `已达前端展示上限 ${MAX_RESULT_KEYS} 条；请缩小匹配模式。` : `已加载 ${keys.length} 条，最多加载 ${MAX_RESULT_KEYS} 条。`}</div><table className="w-full text-left text-xs"><thead className="sticky top-9 bg-[#070b1b] text-[#bfc9e7]/60"><tr><th className="p-3">Key</th><th className="p-3">Type</th><th className="p-3">TTL</th></tr></thead><tbody>{keys.map(item => <tr key={item.key} className={"cursor-pointer border-t border-white/10 hover:bg-white/5 " + (selectedKey === item.key ? "bg-[#0a1ae1]/20" : "")} onClick={() => openKey(item.key)}><td className="break-all p-3 font-mono">{item.key}</td><td className="p-3">{item.type}</td><td className="p-3">{item.persistent ? "永久" : `${item.ttl}s`}</td></tr>)}</tbody></table>{!keys.length ? <p className="py-8 text-center text-sm text-[#bfc9e7]/55">{loading ? "查询中..." : "没有匹配 key"}</p> : null}</div>
      <form className="min-w-0 space-y-4 border-y border-white/10 p-4" onSubmit={saveKey}>
        <h3 className="text-base font-bold">{detail ? "编辑 Key" : "创建 / 更新 Key"}</h3>
        <label className="block text-sm">Key<input required className={control + " mt-2 w-full font-mono"} value={selectedKey} onChange={event => setSelectedKey(event.target.value)} /></label>
        <div className="grid gap-3 sm:grid-cols-[160px_1fr]"><label className="text-sm">Type<select className={control + " mt-2 w-full"} value={keyType} onChange={event => setKeyType(event.target.value)}>{["string", "hash", "list", "set", "zset"].map(item => <option key={item} value={item}>{item}</option>)}</select></label><label className="text-sm">TTL 秒（0 = 永久）<input className={control + " mt-2 w-full"} min={0} type="number" value={ttl} onChange={event => setTtl(event.target.value)} /></label></div>
        <label className="block text-sm">Value（结构化类型使用 JSON）<textarea className="min-h-40 w-full rounded-[6px] border border-[#344375] bg-[#04050b] p-3 font-mono text-sm" rows={8} value={valueText} onChange={event => setValueText(event.target.value)} /></label>
        <div className="flex flex-wrap gap-3"><button className={control + " bg-[#0a1ae1]"} disabled={busy || !selectedKey} type="submit">保存 Key</button><button type="button" className={control} disabled={busy || !detail} onClick={deleteKey}>删除 Key</button><button type="button" className={control} disabled={busy} onClick={() => { setDetail(null); setSelectedKey(""); setKeyType("string"); setValueText(""); }}>清空表单</button></div>
      </form>
    </div>
    <form className="space-y-3 border border-white/10 p-4" onSubmit={uploadFiles}>
      <h3 className="text-base font-bold">文件导入（一次最多 3 个）</h3>
      <p className="text-xs text-[#bfc9e7]/60">文件会以 `prefix:文件名` 写入 string key，并创建 `prefix:文件名:__meta__` 元信息。单文件最大 8MB。</p>
      <div className="grid gap-3 md:grid-cols-[1fr_180px_auto]"><label className="text-sm">Key 前缀<input className={control + " mt-2 w-full font-mono"} value={prefix} onChange={event => setPrefix(event.target.value)} /></label><label className="text-sm">文件<input multiple type="file" className={control + " mt-2 w-full"} onChange={event => setFiles([...(event.target.files ?? [])].slice(0, 3))} /></label><label className="flex items-end gap-2 pb-2 text-sm"><input checked={overwrite} onChange={event => setOverwrite(event.target.checked)} type="checkbox" />覆盖同名 key</label></div>
      <button className={control + " bg-[#0a1ae1]"} disabled={busy || !files.length} type="submit">{busy ? "导入中..." : `导入 ${files.length} 个文件`}</button>
    </form>
  </section>;
}
