"use client";

import { FormEvent, useEffect, useRef, useState } from "react";

export type TableGrant = { database: string; table: string | null; access: "read" | "write" };
type PermissionView = { user_identity:string; tables:TableGrant[]; editable:boolean; message:string; other_grants:string[]; revision:string };
type Api = <T>(path:string,method?:string,body?:unknown,signal?:AbortSignal)=>Promise<T>;
type Operation = { operation_id:string; updated:boolean; status:string; message:string };
const control="min-h-9 rounded-[6px] border border-[#344375] bg-[#070b1b] px-3 py-2 text-sm text-[#dce4f6] disabled:opacity-40";

export function PermissionSelector({instanceId,api,value,onChange,active=true,disabled=false}:{instanceId:string;api:Api;value:TableGrant[];onChange:(rows:TableGrant[])=>void;active?:boolean;disabled?:boolean}) {
  const [databases,setDatabases]=useState<string[]>([]);
  const [tableMap,setTableMap]=useState<Record<string,string[]>>({});
  const [expanded,setExpanded]=useState<Record<string,boolean>>({});
  const [loading,setLoading]=useState("");
  const [error,setError]=useState("");
  const apiRef=useRef(api);
  useEffect(()=>{apiRef.current=api;},[api]);
  useEffect(()=>{
    if(!active)return;
    const controller=new AbortController();
    apiRef.current<string[]>(`/${instanceId}/databases`,"GET",undefined,controller.signal).then(setDatabases).catch(e=>{if(e.name!=="AbortError")setError(e.message);});
    return ()=>controller.abort();
  },[instanceId,active]);
  async function toggle(database:string){
    setExpanded(current=>({...current,[database]:!current[database]}));
    if(tableMap[database])return;
    setLoading(database);setError("");
    try {const rows=await api<string[]>(`/${instanceId}/tables?database=${encodeURIComponent(database)}`);setTableMap(current=>({...current,[database]:rows}));}
    catch(e){setError(e instanceof Error?e.message:"加载库表失败");}finally{setLoading("");}
  }
  function change(database:string,table:string|null,access:string){
    let next=value.filter(item=>!(item.database===database&&item.table===table));
    if(table===null && access){next=next.filter(item=>item.database!==database);}
    if(access)next.push({database,table,access:access as "read"|"write"});
    onChange(next);
  }
  const names=[...new Set([...databases,...value.map(item=>item.database)])].sort();
  return <fieldset disabled={disabled} className="min-w-0 space-y-3">
    <p className="text-xs leading-5 text-[#aab7d1]">各库、各表可分别选择只读或读写。整库“全部表”包含以后新增的表；整库只读时，可额外给部分表读写权限。</p>
    <div className="max-h-80 overflow-auto border-y border-white/10">
      {names.map(database=>{
        const all=value.find(item=>item.database===database&&item.table===null);
        const tableNames=[...new Set([...(tableMap[database]??[]),...value.filter(item=>item.database===database&&item.table!==null).map(item=>item.table!)])].sort();
        return <div key={database} className="border-b border-white/10 py-3">
          <div className="flex min-w-0 flex-wrap items-center gap-3">
            <button type="button" aria-expanded={Boolean(expanded[database])} aria-label={`展开数据库 ${database}`} className="min-w-0 flex-1 basis-40 break-all text-left text-sm" onClick={()=>toggle(database)}>{expanded[database]?"▾":"▸"} {database}</button>
            <label className="flex shrink-0 items-center gap-2 text-xs"><input type="checkbox" aria-label={`${database} 全部表`} checked={Boolean(all)} onChange={event=>change(database,null,event.target.checked?"read":"")} />全部表</label>
            {all?<select aria-label={`${database} 整库权限`} className={control} value={all.access} onChange={event=>change(database,null,event.target.value)}><option value="read">只读</option><option value="write">读写</option></select>:null}
          </div>
          {expanded[database]?<div className="mt-3 space-y-2 pl-3">
            {loading===database?<p className="text-xs">正在加载表...</p>:null}
            {tableNames.map(table=>{
              const row=value.find(item=>item.database===database&&item.table===table);
              return <div key={table} className="flex min-w-0 items-center gap-3"><label className="flex min-w-0 flex-1 items-start gap-2 text-xs"><input aria-label={`${database}.${table} 勾选`} type="checkbox" checked={Boolean(all||row)} disabled={Boolean(all)} onChange={event=>change(database,table,event.target.checked?"read":"")} /><span className="break-all leading-5">{table}</span></label><select aria-label={`${database}.${table} 权限`} className={control+" w-28 shrink-0"} disabled={all?.access==="write"} value={row?.access??(all?"inherit":"")} onChange={event=>change(database,table,event.target.value==="inherit"?"":event.target.value)}>{all?<option value="inherit">{all.access==="write"?"继承读写":"继承只读"}</option>:<option value="">无权限</option>}{!all?<option value="read">只读</option>:null}<option value="write">读写</option></select></div>;
            })}
            {all?.access==="write"?<p className="text-xs text-[#aab7d1]">本库所有表继承读写权限</p>:null}
            {!loading&&!tableNames.length?<p className="text-xs text-[#aab7d1]">暂无表</p>:null}
          </div>:null}
        </div>;
      })}
      {!names.length?<p className="py-6 text-center text-sm text-[#aab7d1]">{error?"库表加载失败":"正在加载数据库..."}</p>:null}
    </div>
    {error?<p role="alert" className="text-sm text-red-300">{error}</p>:null}
    <details className="text-xs" open={value.length>0}><summary>已选 {value.length} 项授权</summary><ul className="mt-2 max-h-32 overflow-auto space-y-2">{value.map(item=><li key={JSON.stringify([item.database,item.table])} className="flex min-w-0 items-start justify-between gap-3"><span className="break-all">{item.database} / {item.table??"全部表（含新增表）"}</span><span className={"shrink-0 "+(item.access==="write"?"text-yellow-300":"text-emerald-300")}>{item.access==="write"?"读写":"只读"}</span></li>)}</ul></details>
  </fieldset>;
}

export function AccountPermissions({instanceId,userIdentity,api,newOperationId,onUpdated}:{instanceId:string;userIdentity:string;api:Api;newOperationId:()=>string;onUpdated:()=>void}) {
  const [view,setView]=useState<PermissionView|null>(null);
  const [loading,setLoading]=useState(false);
  const [error,setError]=useState("");
  const [editing,setEditing]=useState(false);
  const [tables,setTables]=useState<TableGrant[]>([]);
  const [busy,setBusy]=useState(false);
  const [operation,setOperation]=useState<Operation|null>(null);
  const [operationId,setOperationId]=useState("");
  const [message,setMessage]=useState("");
  const dialog=useRef<HTMLDialogElement>(null);
  const generation=useRef(0);
  const key=`infraops:permissions:${instanceId}:${userIdentity}`;
  async function refresh(){
    const revision=++generation.current;setLoading(true);setError("");
    try{const result=await api<PermissionView>(`/${instanceId}/permissions?user_identity=${encodeURIComponent(userIdentity)}`);if(revision===generation.current)setView(result);return result;}
    catch(e){if(revision===generation.current)setError(e instanceof Error?e.message:"查询权限失败");return null;}
    finally{if(revision===generation.current)setLoading(false);}
  }
  async function edit(){
    const current=await refresh();if(!current?.editable)return;
    setTables(current.tables);setOperation(null);setMessage("");setOperationId(newOperationId());setEditing(true);dialog.current?.showModal();
  }
  async function check(action="",id=operationId){
    if(!id)return;setBusy(true);setError("");
    try{const result=await api<Operation>(`/permission-operations/${id}${action?"/"+action:""}`,action?"POST":"GET");setOperation(result);setMessage(result.message);if(result.updated){await refresh();dialog.current?.close();onUpdated();}}
    catch(e){setError(e instanceof Error?e.message:"结果查询失败");}finally{setBusy(false);}
  }
  async function save(event:FormEvent){
    event.preventDefault();if(!view||busy)return;setBusy(true);setError("");sessionStorage.setItem(key,operationId);
    try{const result=await api<Operation>(`/${instanceId}/permissions`,"PUT",{operation_id:operationId,user_identity:userIdentity,revision:view.revision,tables});setOperation(result);setMessage(result.message);if(result.updated){await refresh();dialog.current?.close();onUpdated();}}
    catch(e){setError(e instanceof Error?e.message:"保存失败");await check();}finally{setBusy(false);}
  }
  return <details className="min-w-0 text-xs" onToggle={event=>{if(event.currentTarget.open&&!view&&!loading){const saved=sessionStorage.getItem(key);if(saved){setOperationId(saved);void check("",saved);}void refresh();}}}>
    <summary className="cursor-pointer text-[#b1c1ff]">库表权限</summary>
    <div className="mt-3 min-w-[320px] space-y-3">
      {loading?<p>正在查询当前权限...</p>:null}
      {view?<><ul className="max-h-52 space-y-2 overflow-auto">{view.tables.map(item=><li className="flex justify-between gap-3" key={JSON.stringify([item.database,item.table])}><span className="break-all">{item.database} / {item.table??"全部表（含新增表）"}</span><span className="shrink-0">{item.access==="read"?"只读":item.access==="write"?"读写":"自定义"}</span></li>)}</ul>{!view.tables.length?<p className="text-[#aab7d1]">没有直接库表读写授权</p>:null}{view.message?<p className="max-w-lg whitespace-normal leading-5 text-yellow-300">{view.message}</p>:null}{view.other_grants.length?<details><summary>其他授权</summary><pre className="max-h-40 max-w-lg overflow-auto whitespace-pre-wrap break-all pt-2">{view.other_grants.join("\n")}</pre></details>:null}<div className="flex gap-3"><button type="button" className={control} disabled={!view.editable||loading||busy} onClick={edit}>编辑权限</button><button type="button" className={control} disabled={loading||busy} onClick={()=>refresh()}>刷新</button></div></>:null}
      {message?<p role="status" className="max-w-lg whitespace-normal text-emerald-300">{message}</p>:null}
      {operationId?<div className="space-y-2"><p className="break-all">权限操作：{operationId}{operation?` · ${operation.status}`:""}</p><button type="button" className={control} disabled={busy} onClick={()=>check()}>查询修改结果</button>{operation&&['uncertain','applying'].includes(operation.status)?<div className="flex flex-wrap gap-2"><button type="button" className={control} disabled={busy} onClick={()=>check("verify")}>重新核验</button><button type="button" className={control} disabled={busy} onClick={()=>{if(window.confirm("确认恢复本次修改前的权限？"))void check("restore");}}>恢复修改前权限</button></div>:null}</div>:null}
      {error?<p role="alert" className="max-w-lg whitespace-normal text-red-300">{error}</p>:null}
    </div>
    <dialog ref={dialog} onClose={()=>setEditing(false)} onCancel={event=>{if(busy)event.preventDefault();}} className="m-auto max-h-[90dvh] w-[min(860px,calc(100vw-32px))] overflow-y-auto rounded-[6px] border border-[#4b5fc6] bg-[#070b1b] p-5 text-white backdrop:bg-black/70">
      <form className="space-y-4" onSubmit={save}><h3 className="text-lg font-bold">编辑库表权限</h3><p className="break-all text-sm">{userIdentity}</p>{editing?<PermissionSelector key={operationId} instanceId={instanceId} api={api} value={tables} onChange={setTables} disabled={busy} />:null}<p className="text-xs text-[#aab7d1]">取消勾选会撤销对应授权；保存空列表会移除所有直接库表读写权限。</p>{error?<p role="alert" className="text-sm text-red-300">{error}</p>:null}{message?<p className="text-sm text-yellow-300">{message}</p>:null}<div className="flex justify-end gap-3"><button type="button" className={control} disabled={busy} onClick={()=>dialog.current?.close()}>取消</button><button className={control+" bg-[#0a1ae1]"} disabled={busy||Boolean(operation)}>{busy?"保存并核验...":"保存权限"}</button></div></form>
    </dialog>
  </details>;
}
