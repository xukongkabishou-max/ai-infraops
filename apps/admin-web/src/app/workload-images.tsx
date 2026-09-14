"use client";

import { useMemo, useState } from "react";

export type ControllerImage = {
  controller_type:string;controller_name:string;controller_uid:string|null;controller_key:string;
  controller_created_at:string|null;ownership_resolved:boolean;replica_set:string|null;
  pod_name:string;pod_uid:string|null;node_name:string|null;created_at:string|null;
  desired_replicas:number|null;ready_replicas:number|null;health:string;status:string;phase:string;
  is_ready:boolean;abnormal:boolean;restart_count:number;ready_containers:number;total_containers:number;
  containers:Array<{name:string;container_type:string;image:string;reported_image:string;image_id:string;
    ready:boolean;status:string;restart_count:number;started_at:string|null;abnormal:boolean}>;
};
type Workload={key:string;kind:string;name:string;desired:number|null;created_at:string|null;pods:ControllerImage[];abnormal:number;healthy:number};
const control="min-h-8 rounded-[5px] border border-[#344375] px-3 py-1 text-xs text-[#bfc9e7] disabled:opacity-40";
function age(timestamp:string|null,now:number){
  if(!timestamp)return "未知";
  const seconds=Math.max(0,Math.floor((now-Date.parse(timestamp))/1000));
  if(!Number.isFinite(seconds))return "未知";
  if(seconds<60)return `${seconds} 秒`;
  if(seconds<3600)return `${Math.floor(seconds/60)} 分钟`;
  if(seconds<86400)return `${Math.floor(seconds/3600)} 小时 ${Math.floor(seconds%3600/60)} 分钟`;
  return `${Math.floor(seconds/86400)} 天 ${Math.floor(seconds%86400/3600)} 小时`;
}
function time(timestamp:string|null){return timestamp?new Date(timestamp).toLocaleString("zh-CN",{hour12:false}):"未知";}

function WorkloadGroup({group,now}:{group:Workload;now:number}){
  const [page,setPage]=useState(0);const [expanded,setExpanded]=useState(false);
  const ordered=useMemo(()=>{
    const sorted=[...group.pods].sort((a,b)=>Number(b.abnormal)-Number(a.abnormal)||a.pod_name.localeCompare(b.pod_name));
    // Keep one ready old Pod visible alongside failed rollout Pods in the initial preview.
    if(group.abnormal>=5&&group.healthy>0){const index=sorted.findIndex(pod=>pod.health==="healthy");const [healthy]=sorted.splice(index,1);sorted.splice(4,0,healthy);}
    return sorted;
  },[group]);
  const pageCount=Math.ceil(ordered.length/5);const currentPage=Math.min(page,pageCount-1);
  const visible=ordered.slice(currentPage*5,currentPage*5+5);
  const starting=group.pods.filter(pod=>pod.health==="starting").length;
  const terminating=group.pods.filter(pod=>pod.health==="terminating").length;
  const completed=group.pods.filter(pod=>pod.health==="completed").length;
  return <section className="min-w-0 border-b border-white/15 py-5" aria-label={`${group.kind} ${group.name}`}>
    <header className={"flex flex-wrap items-start justify-between gap-3 border-l-4 px-4 py-3 "+(group.abnormal?"border-red-400 bg-red-500/10":"border-[#344375] bg-white/[0.025]")}>
      <div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><span className="text-xs text-[#bfc9e7]/65">{group.kind}</span><h3 className={"break-all font-mono text-sm font-bold "+(group.abnormal?"text-red-300":"text-[#bfc9e7]")}>{group.name}</h3>{group.abnormal?<span className="text-xs text-red-300">存在异常 Pod</span>:null}</div><p className="mt-2 text-xs text-[#bfc9e7]/65">控制器创建：{time(group.created_at)} · 已存在 {age(group.created_at,now)}</p></div>
      <div className="flex flex-wrap gap-x-5 gap-y-2 text-sm"><span>期望 <b>{group.desired??"未知"}</b></span><span className="text-emerald-300">正常 <b>{group.healthy}</b></span><span className={group.abnormal?"text-red-300":"text-[#bfc9e7]/60"}>异常 <b>{group.abnormal}</b></span>{starting?<span className="text-yellow-300">启动中 {starting}</span>:null}{terminating?<span className="text-[#bfc9e7]/65">终止中 {terminating}</span>:null}{completed?<span className="text-[#bfc9e7]/65">已完成 {completed}</span>:null}</div>
    </header>
    <div className="overflow-x-auto"><table className="w-full min-w-[1100px] table-fixed text-left text-xs"><thead className="text-[#bfc9e7]/60"><tr className="border-b border-white/10"><th className="w-[22%] px-3 py-3">Pod / ReplicaSet</th><th className="w-[15%] px-3 py-3">状态 / 就绪</th><th className="w-[38%] px-3 py-3">容器 / 实际镜像</th><th className="w-[8%] px-3 py-3">重启次数</th><th className="w-[17%] px-3 py-3">Pod 创建时间 / 已部署</th></tr></thead>
      <tbody>{visible.map(pod=><tr key={pod.pod_uid??pod.pod_name} className={"border-b border-white/10 align-top "+(pod.abnormal?"bg-red-500/[0.04]":"")}>
        <td className="break-all px-3 py-3 font-mono leading-6"><span className={pod.abnormal?"text-red-300":"text-[#c9d2f0]"}>{pod.pod_name}</span>{pod.replica_set?<p className="mt-1 text-[#bfc9e7]/50">RS: {pod.replica_set}</p>:null}{pod.node_name?<p className="text-[#bfc9e7]/50">节点: {pod.node_name}</p>:null}{!pod.ownership_resolved?<p className="text-yellow-300">所属控制器信息不完整</p>:null}</td>
        <td className="break-words px-3 py-3 leading-6"><p className={pod.abnormal?"text-red-300":pod.health==="healthy"?"text-emerald-300":"text-yellow-300"}>{pod.status}</p><p className="text-[#bfc9e7]/65">就绪 {pod.ready_containers}/{pod.total_containers}</p></td>
        <td className="px-3 py-3"><div className="space-y-3">{pod.containers.map(container=><div key={`${container.container_type}:${container.name}`}><p className={container.abnormal?"text-red-300":"text-[#bfc9e7]/65"}>{container.container_type==="init"?"Init · ":""}{container.name} · {container.status}{container.restart_count?` · 重启 ${container.restart_count}`:""}</p><p className={"mt-1 break-all font-mono leading-5 "+(container.abnormal?"text-red-300":"text-[#c9d2f0]")} title={container.image_id||undefined}>{container.image||"镜像未提供"}</p></div>)}</div></td>
        <td className="px-3 py-3 font-mono tabular-nums">{pod.restart_count}</td><td className="px-3 py-3 leading-6"><p>{time(pod.created_at)}</p><p className="text-[#bfc9e7]/60">{age(pod.created_at,now)}</p></td>
      </tr>)}</tbody>
    </table></div>
    {ordered.length>5?<footer className="mt-3 flex flex-wrap items-center justify-end gap-3 text-xs text-[#bfc9e7]/65"><span>共 {ordered.length} 个 Pod · 当前 {currentPage*5+1}-{Math.min((currentPage+1)*5,ordered.length)}</span>{!expanded?<button type="button" className={control} onClick={()=>{setExpanded(true);setPage(1);}}>查看其余 {ordered.length-5} 个 Pod</button>:<><button type="button" className={control} disabled={currentPage===0} onClick={()=>setPage(currentPage-1)}>上一组</button><span>{currentPage+1}/{pageCount}</span><button type="button" className={control} disabled={currentPage+1>=pageCount} onClick={()=>setPage(currentPage+1)}>下一组</button><button type="button" className={control} onClick={()=>{setExpanded(false);setPage(0);}}>收起</button></>}</footer>:null}
  </section>;
}

export function WorkloadImages({images,observedAt}:{images:ControllerImage[];observedAt:number}){
  const groups=useMemo(()=>{
    const byController=new Map<string,Workload>();
    for(const pod of images){const key=pod.controller_key;let group=byController.get(key);if(!group){group={key,kind:pod.controller_type,name:pod.controller_name,desired:pod.desired_replicas,created_at:pod.controller_created_at,pods:[],abnormal:0,healthy:0};byController.set(key,group);}group.pods.push(pod);group.abnormal+=Number(pod.abnormal);group.healthy+=Number(pod.health==="healthy");}
    return [...byController.values()].sort((a,b)=>Number(b.abnormal>0)-Number(a.abnormal>0)||a.name.localeCompare(b.name)||a.key.localeCompare(b.key));
  },[images]);
  return <div className="mt-5 min-w-0"><div className="flex flex-wrap gap-x-5 gap-y-2 border-b border-white/10 pb-3 text-xs text-[#bfc9e7]/65"><span>控制器 {groups.length}</span><span className="text-red-300">异常控制器 {groups.filter(group=>group.abnormal>0).length}</span><span>Pod {images.length}</span><span>采集时间：{new Date(observedAt).toLocaleString("zh-CN",{hour12:false})}</span></div><p className="mt-3 text-xs leading-5 text-[#bfc9e7]/60">正常表示 Pod 当前就绪。滚动发布期间 Pod 总数可能超过期望副本；同一控制器的新旧 Pod 和各自镜像在同组显示。已部署时长从 Pod 创建时间计算。</p>{groups.map(group=><WorkloadGroup key={`${observedAt}:${group.key}`} group={group} now={observedAt} />)}{!groups.length?<p className="py-10 text-center text-sm text-[#bfc9e7]/60">该 namespace 当前没有 Pod</p>:null}</div>;
}
