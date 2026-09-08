"use client";

import { useState } from "react";
import Link from "next/link";

export function ApprovalLink({ requestId }: { requestId: number }) {
  const [message, setMessage] = useState("");
  const [manualLink, setManualLink] = useState("");
  async function copy() {
    const configured = process.env.NEXT_PUBLIC_APPROVAL_PORTAL_URL?.trim();
    const origin = new URL(configured || window.location.origin).origin;
    const link = new URL(`/approvals/${requestId}`, origin).href;
    try {
      await navigator.clipboard.writeText(link);
      setMessage("审批链接已复制"); setManualLink("");
    } catch {
      setManualLink(link); setMessage("请选择链接复制");
    }
  }
  return <div className="flex min-w-0 flex-wrap items-center gap-3 text-xs">
    <Link href={`/approvals/${requestId}`} prefetch={false} className="text-[#9fb0ff] underline underline-offset-4">审批详情</Link>
    <button type="button" className="min-h-9 rounded-[6px] border border-[#4b5fc6] px-3 py-2 font-bold text-[#c9d2f0]" onClick={copy}>复制审批链接</button>
    {message ? <span role="status" className="text-emerald-300">{message}</span> : null}
    {manualLink ? <input aria-label="审批链接" readOnly value={manualLink} onFocus={event => event.target.select()} className="min-w-0 w-full border border-white/20 bg-[#04050b] p-2 text-sm" /> : null}
  </div>;
}
