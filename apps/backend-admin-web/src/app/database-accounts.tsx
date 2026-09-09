"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { AccountPermissions, PermissionSelector, type TableGrant } from "./database-permissions";

type Instance = { id: number; middleware_type: string; instance_name: string; environment_name: string; base_url: string };
type Account = { user_identity: string; username: string; host: string; password: string | null; password_updated_at: string | null; expires_at: string | null; status: string; comment: string; last_error?: string; roles: string[]; privileges: Array<{scope: string; value: string}> };
type Operation = { operation_id: string; status: string; created: boolean; user_identity: string; password?: string; message: string };
function operationId() {
  const bytes=crypto.getRandomValues(new Uint8Array(16));bytes[6]=(bytes[6]&15)|64;bytes[8]=(bytes[8]&63)|128;
  const hex=[...bytes].map(value=>value.toString(16).padStart(2,"0")).join("");return `${hex.slice(0,8)}-${hex.slice(8,12)}-${hex.slice(12,16)}-${hex.slice(16,20)}-${hex.slice(20)}`;
}
const control = "min-h-10 rounded-[6px] border border-[#344375] bg-[#070b1b] px-3 py-2 text-sm text-[#dce4f6] disabled:opacity-40";
const field = "mt-2 w-full " + control;
const formatTime = (value: string | null) => value ? new Date(value).toLocaleString("zh-CN", {hour12:false}) : "-";
const states: Record<string,string> = {existing:"已有账号",recorded:"已登记",instance_credential:"实例管理账号",active:"有效",expired:"已到期",expiring:"到期处理中",failed:"未创建 / 已撤销",cleanup_required:"待清理",provisioning:"创建中",verifying:"核验中",uncertain:"结果待核验"};

export function DatabaseAccounts({accessToken,apiBaseUrl}:{accessToken:string;apiBaseUrl:string}) {
  const [instances,setInstances]=useState<Instance[]>([]);
  const [kind,setKind]=useState("mysql");
  const [instanceId,setInstanceId]=useState("");
  const [rows,setRows]=useState<Account[]>([]);
  const [total,setTotal]=useState(0);
  const [page,setPage]=useState(1);
  const [keyword,setKeyword]=useState("");
  const [loading,setLoading]=useState(false);
  const [loaded,setLoaded]=useState(false);
  const [capability,setCapability]=useState<{current_user:string;can_manage:boolean;message:string}|null>(null);
  const [error,setError]=useState("");
  const [notice,setNotice]=useState("");
  const [created,setCreated]=useState<{user_identity:string;password:string}|null>(null);
  const [operation,setOperation]=useState<Operation|null>(null);
  const [lastOperation,setLastOperation]=useState("");
  const [operationBusy,setOperationBusy]=useState(false);
  const formOperation=useRef("");
  const [formActive,setFormActive]=useState(false);
  const [busy,setBusy]=useState(false);
  const [formError,setFormError]=useState("");
  const [username,setUsername]=useState("");
  const [host,setHost]=useState("%");
  const [source,setSource]=useState<Account|null>(null);
  const [manual,setManual]=useState(false);
  const [password,setPassword]=useState("");
  const [limited,setLimited]=useState(false);
  const [days,setDays]=useState(30);
  const [tables,setTables]=useState<TableGrant[]>([]);
  const [record,setRecord]=useState<Account|null>(null);
  const [recordPassword,setRecordPassword]=useState("");
  const dialog=useRef<HTMLDialogElement>(null);
  const passwordDialog=useRef<HTMLDialogElement>(null);
  const generation=useRef(0);
  const requestController=useRef<AbortController|null>(null);
  const prefix="/api/admin/database-accounts";

  async function api<T>(path:string,method="GET",body?:unknown,signal?:AbortSignal):Promise<T> {
    const response=await fetch(apiBaseUrl+prefix+path,{method,signal:signal??AbortSignal.timeout(90000),cache:"no-store",headers:{Authorization:`Bearer ${accessToken}`,"Content-Type":"application/json"},body:body===undefined?undefined:JSON.stringify(body)});
    const data=await response.json();
    if(!response.ok) throw new Error(typeof data.detail==="string"?data.detail:data.detail?.message??"操作失败");
    return data;
  }
  useEffect(()=>{
    const controller=new AbortController();
    fetch(apiBaseUrl+prefix+"/instances",{signal:controller.signal,cache:"no-store",headers:{Authorization:`Bearer ${accessToken}`}}).then(async response=>{
      const data=await response.json();if(!response.ok) throw new Error(data.detail??"加载实例失败");return data as Instance[];
    }).then(rows=>{setInstances(rows);setLastOperation(sessionStorage.getItem("infraops:database-operation")??"");}).catch(e=>{if(e.name!=="AbortError")setError(e.message);});
    const revision=generation;
    return ()=>{controller.abort();requestController.current?.abort();revision.current++;};
  },[accessToken,apiBaseUrl]);
  function changeInstance(value:string) {
    generation.current++;requestController.current?.abort();setInstanceId(value);setRows([]);setTotal(0);setLoaded(false);setCapability(null);setPage(1);setLoading(false);setError("");setNotice("");setCreated(null);
  }
  async function load(nextPage=1) {
    if(!instanceId)return;
    requestController.current?.abort();const controller=new AbortController();requestController.current=controller;
    const revision=++generation.current;setLoading(true);setError("");
    try {
      const data=await api<{items:Account[];total:number;capabilities:{current_user:string;can_manage:boolean;message:string}}>(`/${instanceId}/accounts?page=${nextPage}&keyword=${encodeURIComponent(keyword)}`,"GET",undefined,controller.signal);
      if(revision===generation.current){setRows(data.items);setTotal(data.total);setPage(nextPage);setLoaded(true);setCapability(data.capabilities);}
    } catch(e){if(revision===generation.current && e instanceof Error && e.name!=="AbortError")setError(e.message);}
    finally {if(revision===generation.current)setLoading(false);}
  }
  async function openCreate(account:Account|null) {
    formOperation.current=operationId();
    setSource(account);setUsername("");setHost(account?.host||"%");setManual(false);setPassword("");setLimited(false);setDays(30);setTables([]);setFormError("");setFormActive(true);dialog.current?.showModal();
  }
  async function create(event:FormEvent){
    event.preventDefault();if(busy)return;setBusy(true);setFormError("");
    const opId=formOperation.current;setLastOperation(opId);sessionStorage.setItem("infraops:database-operation",opId);setOperation(null);
    try{
      const result=await api<Operation>(`/${instanceId}/accounts`,"POST",{operation_id:opId,username,host,source_identity:source?.user_identity??null,tables:source?[]:tables,password:manual?password:null,expires_days:limited?days:null});
      setOperation(result);
      if(!result.created){setFormError(`操作状态：${states[result.status]??result.status}，可按操作编号继续查询`);return;}
      dialog.current?.close();setCreated({user_identity:result.user_identity,password:result.password??""});setNotice(`已核验 ${result.user_identity} 的账号、权限及密码记录`);await load(1);
    }catch(e){setFormError(e instanceof Error?e.message:"创建失败");try{const result=await api<Operation>(`/operations/${opId}`);setOperation(result);if(result.created){dialog.current?.close();setCreated({user_identity:result.user_identity,password:result.password??""});setNotice("请求响应中断，已从操作记录确认创建成功");await load(1);}}catch{setOperation(null);}}finally{setBusy(false);}
  }
  async function lookupOperation(action=""){
    if(!lastOperation)return;setOperationBusy(true);setError("");
    try{const result=await api<Operation>(`/operations/${lastOperation}${action?"/"+action:""}`,action?"POST":"GET");setOperation(result);if(result.created)setCreated({user_identity:result.user_identity,password:result.password??""});}
    catch(e){setError(e instanceof Error?e.message:"结果查询失败");}finally{setOperationBusy(false);}
  }
  async function saveRecord(event:FormEvent){
    event.preventDefault();if(busy||!record)return;setBusy(true);setFormError("");
    try{await api(`/${instanceId}/password-record`,"PUT",{user_identity:record.user_identity,password:recordPassword});passwordDialog.current?.close();setRecordPassword("");setNotice("密码记录已保存");await load(page);}
    catch(e){setFormError(e instanceof Error?e.message:"保存失败");}finally{setBusy(false);}
  }
  function exportPage(){
    const quote=(value:string)=>'"'+value.replaceAll('"','""')+'"';
    const contents=[["账号","来源主机","最后登记密码","密码登记时间","到期时间"],...rows.map(row=>[row.username,row.host,row.password??"待手动添加",formatTime(row.password_updated_at),row.expires_at?formatTime(row.expires_at):"永久"])].map(row=>row.map(value=>quote(/^[=+@\-]/.test(value)?"'"+value:value)).join(",")).join("\r\n");
    const url=URL.createObjectURL(new Blob(["\uFEFF",contents],{type:"text/csv;charset=utf-8"}));const link=document.createElement("a");link.href=url;link.download=`${kind}-accounts-${instanceId}-${page}.csv`;link.click();URL.revokeObjectURL(url);
  }
  const instance=instances.find(item=>String(item.id)===instanceId);
  return <section className="min-w-0 space-y-4">
    <div className="flex flex-wrap items-center gap-3"><h2 className="mr-auto text-lg font-bold">MySQL / Doris 账号管理</h2><button className={control} disabled={!rows.length||loading} onClick={exportPage}>导出本页</button><button className={control+" bg-[#0a1ae1]"} disabled={!capability?.can_manage||loading||busy} onClick={()=>openCreate(null)}>新建账号</button></div>
    <div className="flex gap-2" role="tablist" aria-label="数据库类型">{[["mysql","MySQL"],["doris","Doris"]].map(([value,label])=><button key={value} role="tab" aria-selected={kind===value} className={control+(kind===value?" border-[#7891ff] bg-[#17204e]":"")} onClick={()=>{setKind(value);changeInstance("");}}>{label}</button>)}</div>
    <form className="flex flex-wrap items-end gap-3" onSubmit={event=>{event.preventDefault();void load();}}><label className="min-w-0 flex-1 basis-72 text-sm">环境 / 实例<select className={field} value={instanceId} onChange={event=>changeInstance(event.target.value)}><option value="">请选择数据库实例</option>{instances.filter(item=>item.middleware_type===kind).map(item=><option key={item.id} value={item.id}>{item.environment_name} / {item.instance_name}</option>)}</select></label><label className="text-sm">账号筛选<input className={field} value={keyword} onChange={event=>setKeyword(event.target.value)} placeholder="账号或 Host" /></label><button className={control} disabled={!instanceId||loading}>{loading?"查询中...":"查询账号"}</button></form>
    {instance?<p className="break-all text-xs text-[#aab7d1]">{instance.base_url}</p>:null}
    {capability?<p className={"break-words border-l-2 py-2 pl-3 text-sm "+(capability.can_manage?"border-emerald-400 text-emerald-300":"border-yellow-400 text-yellow-300")}>数据库实际账号：{capability.current_user} · {capability.can_manage?"已具备账号授权能力":capability.message}</p>:null}
    {error?<p role="alert" className="text-sm text-red-300">{error}</p>:null}{notice?<p role="status" className="text-sm text-emerald-300">{notice}</p>:null}
    {created?<div className="flex flex-wrap items-center gap-3 border-y border-emerald-400/30 py-3 text-sm"><span>{created.user_identity}</span><span className="break-all font-mono">密码：{created.password}</span><button className="ml-auto text-xs text-[#aab7d1]" onClick={()=>setCreated(null)}>收起</button></div>:null}
    {lastOperation?<div className="space-y-2 border-y border-white/10 py-3 text-xs"><p className="break-all">操作编号：{lastOperation}{operation?` · ${states[operation.status]??operation.status}`:""}</p>{operation?.message?<p className="text-yellow-300">{operation.message}</p>:null}<div className="flex flex-wrap gap-3"><button disabled={operationBusy||busy} className={control} onClick={()=>lookupOperation()}>查询结果</button>{operation && ["uncertain","cleanup_required","provisioning","verifying"].includes(operation.status)?<button disabled={operationBusy||busy} className={control} onClick={()=>lookupOperation("verify")}>重新核验</button>:null}{operation && ["uncertain","cleanup_required"].includes(operation.status)?<button disabled={operationBusy||busy} className={control} onClick={()=>{if(window.confirm(`确认撤销本次未完成创建的账号 ${operation.user_identity}？`))void lookupOperation("rollback");}}>撤销未完成创建</button>:null}</div></div>:null}
    <div className="overflow-auto border-y border-white/10"><table className="w-full min-w-[950px] text-left text-sm"><thead className="text-xs text-[#aab7d1]"><tr>{["账号 / Host","最后登记密码","登记时间","到期时间","状态","库表权限","操作"].map(label=><th className="px-3 py-3" key={label}>{label}</th>)}</tr></thead><tbody>{rows.map(row=><tr key={row.user_identity} className="border-t border-white/10 align-top"><td className="px-3 py-3"><span className="font-mono">{row.username}</span><p className="mt-1 text-xs text-[#aab7d1]">{row.host}</p></td><td className="max-w-64 break-all px-3 py-3 font-mono">{row.password??<span className="font-sans text-yellow-300">待手动添加</span>}</td><td className="px-3 py-3 text-xs">{formatTime(row.password_updated_at)}</td><td className="px-3 py-3 text-xs">{row.expires_at?formatTime(row.expires_at):"永久"}</td><td className="px-3 py-3 text-xs"><span className={row.status==="expired"?"text-yellow-300":"text-emerald-300"}>{states[row.status]??row.status}</span>{row.last_error?<p className="mt-2 max-w-48 text-red-300">{row.last_error}</p>:null}</td><td className="px-3 py-3"><AccountPermissions key={`${instanceId}:${row.user_identity}`} instanceId={instanceId} userIdentity={row.user_identity} api={api} newOperationId={operationId} onUpdated={()=>setNotice("权限修改已核验")} /></td><td className="px-3 py-3"><div className="flex flex-wrap gap-3 text-xs text-[#b1c1ff]"><button disabled={!capability?.can_manage||loading} className="disabled:opacity-40" onClick={()=>openCreate(row)}>克隆账号</button><button onClick={()=>{setRecord(row);setRecordPassword(row.password??"");setFormError("");passwordDialog.current?.showModal();}}>登记密码</button></div></td></tr>)}</tbody></table>{!rows.length?<p className="py-10 text-center text-sm text-[#aab7d1]">{loading?"正在查询...":loaded?"没有匹配的账号":"请选择实例并查询"}</p>:null}</div>
    {loaded?<div className="flex items-center justify-end gap-3 text-xs"><span>共 {total} 个账号 · 第 {page} 页</span><button className={control} disabled={page===1||loading} onClick={()=>load(page-1)}>上一页</button><button className={control} disabled={page*20>=total||loading} onClick={()=>load(page+1)}>下一页</button></div>:null}
    <dialog ref={dialog} onClose={()=>setFormActive(false)} onCancel={event=>{if(busy)event.preventDefault();}} className="m-auto max-h-[90dvh] w-[min(780px,calc(100vw-32px))] overflow-y-auto rounded-[6px] border border-[#4b5fc6] bg-[#070b1b] p-5 text-white backdrop:bg-black/70"><form onSubmit={create} className="space-y-5"><h3 className="text-lg font-bold">{source?"克隆账号权限":"新建数据库账号"}</h3><p className="break-all text-sm text-[#aab7d1]">{instance?.environment_name} / {instance?.instance_name}{source?` · 源账号 ${source.user_identity}`:""}</p>
      <div className="grid gap-4 sm:grid-cols-2"><label className="text-sm">新账号名称 *<input required pattern="[A-Za-z][A-Za-z0-9_]{1,31}" maxLength={32} className={field} value={username} onChange={event=>setUsername(event.target.value)} placeholder="例如 app_reader" /></label><label className="text-sm">允许连接的 Host<input required maxLength={60} className={field} value={host} onChange={event=>setHost(event.target.value)} /></label></div>
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={manual} onChange={event=>setManual(event.target.checked)} />管理员指定密码</label>{manual?<label className="block text-sm">密码 *<input type="text" autoComplete="off" required minLength={8} maxLength={128} className={field} value={password} onChange={event=>setPassword(event.target.value)} /></label>:<p className="text-sm text-[#aab7d1]">自动生成 8 位随机密码，包含大小写字母、数字及符号</p>}
      <div className="flex flex-wrap items-center gap-4"><label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={limited} onChange={event=>setLimited(event.target.checked)} />设置到期时间</label>{limited?<label className="flex items-center gap-2 text-sm"><input className={control+" w-24"} type="number" required min={1} max={3650} value={days} onChange={event=>setDays(Number(event.target.value))} />天后到期</label>:<span className="text-sm text-[#aab7d1]">永久</span>}</div>
      {!source&&formActive?<PermissionSelector instanceId={instanceId} api={api} value={tables} onChange={setTables} disabled={busy} />:null}
      {formError?<p role="alert" className="text-sm text-red-300">{formError}</p>:null}<div className="flex justify-end gap-3"><button type="button" className={control} disabled={busy} onClick={()=>dialog.current?.close()}>取消</button><button className={control+" bg-[#0a1ae1]"} disabled={busy||(!source&&!tables.length)}>{busy?"创建中...":"确认创建"}</button></div>
    </form></dialog>
    <dialog ref={passwordDialog} onCancel={event=>{if(busy)event.preventDefault();}} className="m-auto w-[min(500px,calc(100vw-32px))] rounded-[6px] border border-[#4b5fc6] bg-[#070b1b] p-5 text-white backdrop:bg-black/70"><form onSubmit={saveRecord} className="space-y-4"><h3 className="text-lg font-bold">登记已有密码</h3><p className="break-all text-sm">{record?.user_identity}</p><label className="block text-sm">最后配置的密码<input type="text" autoComplete="off" required maxLength={256} className={field} value={recordPassword} onChange={event=>setRecordPassword(event.target.value)} /></label><p className="text-xs text-[#aab7d1]">仅保存管理记录，不修改数据库中的密码</p>{formError?<p role="alert" className="text-sm text-red-300">{formError}</p>:null}<div className="flex justify-end gap-3"><button type="button" className={control} disabled={busy} onClick={()=>passwordDialog.current?.close()}>取消</button><button className={control+" bg-[#0a1ae1]"} disabled={busy}>{busy?"保存中...":"保存记录"}</button></div></form></dialog>
  </section>;
}
