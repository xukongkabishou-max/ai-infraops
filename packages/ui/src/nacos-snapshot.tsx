export type NacosConfiguration = {
  format: string;
  content: string;
  line_numbers: "source" | "display";
  approved_lines: number[];
  historical_reconstruction: boolean;
};

export function NacosSnapshot({configuration}:{configuration:NacosConfiguration}) {
  const approved=new Set(configuration.approved_lines);
  const lines=configuration.content.split(/\r?\n/);
  if(lines[lines.length-1]==="")lines.pop();
  return <div className="min-w-0 space-y-2">
    <p className="text-xs leading-5 text-[#bfc9e7]">{configuration.historical_reconstruction?"历史记录仅保存获批字段，以下按配置路径还原；左侧为展示行号。":"左侧为原文行号；绿色为获批值所在行，其余值保留脱敏。"}</p>
    <div className="max-h-[560px] overflow-auto border border-white/10 bg-[#04050b] py-3 font-mono text-sm leading-6" role="region" aria-label="审批配置快照">
      {lines.map((line,index)=><div key={index} className="grid min-w-max grid-cols-[4rem_1fr]"><span className={"sticky left-0 select-none border-r border-white/10 bg-[#04050b] pr-3 text-right tabular-nums "+(approved.has(index+1)?"text-emerald-300":"text-[#bfc9e7]/45")}>{index+1}</span><code className="whitespace-pre px-4 text-[#e0e6f5]">{line||" "}</code></div>)}
    </div>
  </div>;
}
