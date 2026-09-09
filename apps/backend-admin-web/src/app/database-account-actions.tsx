"use client";

import { FormEvent, useRef, useState } from "react";

type Api=<T>(path:string,method?:string,body?:unknown,signal?:AbortSignal)=>Promise<T>;
type Preview={user_identity:string;protected:boolean;revision:string;disabled:boolean;disable_method:string};
type Outcome={operation_id:string;action:string;status:string;confirmed:boolean;message:string};
const control="min-h-9 rounded-[6px] border border-[#344375] bg-[#070b1b] px-3 py-2 text-sm text-[#dce4f6] disabled:opacity-40";
const modal="m-auto max-h-[90dvh] w-[min(540px,calc(100vw-32px))] overflow-y-auto rounded-[6px] border border-[#4b5fc6] bg-[#070b1b] p-5 text-white backdrop:bg-black/70";

export function DatabaseAccountActions({instanceId,userIdentity,username,api,newOperationId,onDone}:{instanceId:string;userIdentity:string;username:string;api:Api;newOperationId:()=>string;onDone:(message:string)=>void}){
  const [action,setAction]=useState<"disable"|"delete">("disable");
  const [preview,setPreview]=useState<Preview|null>(null);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const [confirmation,setConfirmation]=useState("");
  const [operationId,setOperationId]=useState("");
  const [outcome,setOutcome]=useState<Outcome|null>(null);
  const reviewDialog=useRef<HTMLDialogElement>(null);
  const confirmDialog=useRef<HTMLDialogElement>(null);
  const storageKey=`infraops:account-action:${instanceId}:${userIdentity}`;
  const protectedName=['root','admin','mysql.sys','mysql.session','mysql.infoschema'].includes(username.toLowerCase());
  async function open(next:"disable"|"delete"){
    setAction(next);setPreview(null);setError("");setOutcome(null);setBusy(true);setConfirmation("");reviewDialog.current?.showModal();
    try{const result=await api<Preview>(`/${instanceId}/accounts/action-preview?user_identity=${encodeURIComponent(userIdentity)}`);setPreview(result);setOperationId(newOperationId());if(result.protected)setError("不能操作数据库内置管理账号或当前实例使用的管理账号");}
    catch(e){setError(e instanceof Error?e.message:"无法读取账号状态");}finally{setBusy(false);}
  }
  async function queryResult(verify=false,id=operationId){
    if(!id)return;setBusy(true);setError("");
    try{const result=await api<Outcome>(`/account-actions/${id}${verify?"/verify":""}`,verify?"POST":"GET");setOutcome(result);if(result.confirmed){confirmDialog.current?.close();reviewDialog.current?.close();onDone(result.message);}}
    catch(e){setError(e instanceof Error?e.message:"无法查询结果");}finally{setBusy(false);}
  }
  async function submit(event:FormEvent){
    event.preventDefault();if(busy||!preview||confirmation!==userIdentity)return;setBusy(true);setError("");sessionStorage.setItem(storageKey,operationId);
    try{const result=await api<Outcome>(`/${instanceId}/accounts/actions`,"POST",{operation_id:operationId,action,user_identity:userIdentity,confirm_identity:confirmation,revision:preview.revision});setOutcome(result);if(result.confirmed){confirmDialog.current?.close();onDone(result.message);}}
    catch(e){setError(e instanceof Error?e.message:"操作未确认成功");try{await queryResult();}catch{}}finally{setBusy(false);}
  }
  const label=action==="delete"?"删除":"禁用";
  return <div className="space-y-2">
    <div className="flex flex-wrap gap-3"><button type="button" disabled={protectedName||busy} className="text-yellow-300 disabled:opacity-40" onClick={()=>open("disable")}>禁用账号</button><button type="button" disabled={protectedName||busy} className="text-red-300 disabled:opacity-40" onClick={()=>open("delete")}>删除账号</button></div>
    <details onToggle={event=>{if(event.currentTarget.open){const saved=sessionStorage.getItem(storageKey);if(saved&&!operationId){setOperationId(saved);void queryResult(false,saved);}}}}><summary className="cursor-pointer text-[#aab7d1]">禁用 / 删除结果</summary>{operationId?<div className="mt-2 space-y-2"><p className="break-all">{operationId}</p>{outcome?<p className="max-w-64 whitespace-normal">{outcome.message}</p>:null}<button className={control} disabled={busy} onClick={()=>queryResult()}>查询结果</button><button className={control} disabled={busy} onClick={()=>queryResult(true)}>只读核验</button></div>:<p className="mt-2">本标签页暂无操作记录</p>}</details>
    <dialog ref={reviewDialog} className={modal} onCancel={event=>{if(busy)event.preventDefault();}}><div className="space-y-4"><h3 className="text-lg font-bold">{label}账号</h3><p className="break-all text-sm">目标账号：{userIdentity}</p><p className="text-sm leading-6">{action==="delete"?"删除后，该数据库账号及其授权将移除。业务库表和平台审计记录保留。":"禁用后阻止新的登录，保留账号及授权；已经建立的数据库连接不会强制断开。"}</p>{action==="disable"&&preview?<p className="text-xs text-yellow-300">{preview.disable_method}。Doris 禁用会把密码期限改为立即过期，不更换原密码。</p>:null}{error?<p role="alert" className="text-sm text-red-300">{error}</p>:null}<div className="flex justify-end gap-3"><button type="button" className={control} disabled={busy} onClick={()=>reviewDialog.current?.close()}>取消</button><button type="button" className={control} disabled={busy||!preview||preview.protected} onClick={()=>{reviewDialog.current?.close();confirmDialog.current?.showModal();}}>继续确认</button></div></div></dialog>
    <dialog ref={confirmDialog} className={modal} onCancel={event=>{if(busy)event.preventDefault();}}><form className="space-y-4" onSubmit={submit}><h3 className="text-lg font-bold">再次确认{label}</h3><p className="break-all text-sm">{userIdentity}</p><label className="block text-sm">输入完整账号标识以确认<input aria-label="确认目标账号" autoComplete="off" required className={control+" mt-2 w-full"} placeholder={userIdentity} value={confirmation} onChange={event=>setConfirmation(event.target.value)} /></label>{error?<p role="alert" className="text-sm text-red-300">{error}</p>:null}{outcome?<p role="status" className="text-sm text-yellow-300">{outcome.message} · {outcome.operation_id}</p>:null}<div className="flex flex-wrap justify-end gap-3"><button type="button" className={control} disabled={busy} onClick={()=>confirmDialog.current?.close()}>取消</button>{outcome&&!outcome.confirmed?<button type="button" className={control} disabled={busy} onClick={()=>queryResult(true)}>核验原操作</button>:<button className={control+(action==="delete"?" border-red-400 text-red-300":" border-yellow-400 text-yellow-300")} disabled={busy||confirmation!==userIdentity}>{busy?"执行并核验...":`确认${label}`}</button>}</div></form></dialog>
  </div>;
}
