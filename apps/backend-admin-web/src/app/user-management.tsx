"use client";

import { FormEvent, useEffect, useRef, useState } from "react";

type User = {
  id: number; username: string; display_name: string; is_active: boolean | number;
  is_superuser: boolean | number; last_login_at: string | null;
  has_stored_password: boolean | number; password_changed_at: string | null;
};
const control = "min-h-10 rounded-[6px] border border-[#4b5fc6] px-3 py-2 text-sm font-bold text-[#c9d2f0] disabled:opacity-40";
const inputClass = "mt-2 h-11 w-full rounded-[6px] border border-white/20 bg-[#04050b] px-3 font-mono text-white";
function time(value: string | null) {
  if (!value) return "-";
  return new Date(/(?:Z|[+-]\d{2}:\d{2})$/i.test(value) ? value : `${value}Z`).toLocaleString("zh-CN", { hour12: false });
}

export function UserManagement({ accessToken, apiBaseUrl, currentUserId, canResetPasswords, canViewPasswords, onOwnPasswordChanged }: {
  accessToken: string; apiBaseUrl: string; currentUserId: number; canResetPasswords: boolean; canViewPasswords: boolean;
  onOwnPasswordChanged: () => void;
}) {
  const [users, setUsers] = useState<User[]>([]);
  const [revision, setRevision] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [selected, setSelected] = useState<User | null>(null);
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [formError, setFormError] = useState("");
  const [saving, setSaving] = useState(false);
  const [reading, setReading] = useState<number | null>(null);
  const [visiblePasswords, setVisiblePasswords] = useState<Record<number, string>>({});
  const dialog = useRef<HTMLDialogElement>(null);
  const operator = users.find(user => user.id === currentUserId);
  const mayReset = canResetPasswords && Boolean(operator?.is_active && operator?.is_superuser);
  const mayView = canViewPasswords && mayReset && operator?.username === "admin";
  useEffect(() => {
    const controller = new AbortController();
    fetch(`${apiBaseUrl}/api/rbac/users`, { headers: { Authorization: `Bearer ${accessToken}` }, cache: "no-store", signal: controller.signal })
      .then(async response => {
        const data = await response.json();
        if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "用户加载失败");
        if (!controller.signal.aborted) { setUsers(data); setError(""); }
      })
      .catch(e => { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : "用户加载失败"); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [accessToken, apiBaseUrl, revision]);
  useEffect(() => {
    const hide = () => { if (document.hidden) setVisiblePasswords({}); };
    document.addEventListener("visibilitychange", hide);
    return () => document.removeEventListener("visibilitychange", hide);
  }, []);
  function open(user: User) {
    setSelected(user); setPassword(""); setConfirmation(""); setFormError("");
    dialog.current?.showModal();
  }
  async function save(event: FormEvent) {
    event.preventDefault();
    if (!selected || saving) return;
    if (!password.trim() || new TextEncoder().encode(password).length > 72) { setFormError("密码不能为空，且不能超过 72 个 UTF-8 字节"); return; }
    if (password !== confirmation) { setFormError("两次输入的密码不一致"); return; }
    setSaving(true); setFormError("");
    try {
      const response = await fetch(`${apiBaseUrl}/api/rbac/users/${selected.id}/password`, {
        method: "PUT", headers: { Authorization: `Bearer ${accessToken}`, "Content-Type": "application/json" },
        body: JSON.stringify({ new_password: password, confirm_password: confirmation }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "密码修改失败");
      dialog.current?.close();
      setVisiblePasswords({});
      if (data.reauthenticate) { onOwnPasswordChanged(); return; }
      setNotice(`${selected.username} 的密码已修改，原有登录会话已失效`);
      setRevision(value => value + 1);
    } catch (e) { setFormError(e instanceof Error ? e.message : "密码修改失败"); }
    finally { setSaving(false); }
  }
  async function reveal(user: User) {
    if (visiblePasswords[user.id] !== undefined) {
      setVisiblePasswords(current => { const next = { ...current }; delete next[user.id]; return next; }); return;
    }
    setReading(user.id); setError("");
    try {
      const response = await fetch(`${apiBaseUrl}/api/rbac/users/${user.id}/password`, { headers: { Authorization: `Bearer ${accessToken}` }, cache: "no-store" });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "密码读取失败");
      if (data.available && !document.hidden) setVisiblePasswords(current => ({ ...current, [user.id]: data.password }));
      else if (!data.available) setNotice(`${user.username} 的当前密码未记录，重设后可查看`);
    } catch (e) { setVisiblePasswords({}); setError(e instanceof Error ? e.message : "密码读取失败"); }
    finally { setReading(null); }
  }
  return <section className="min-w-0 space-y-5">
    <div className="flex items-center justify-between gap-4"><h2 className="text-lg font-bold">用户列表 · {users.length}</h2><button className={control} onClick={() => { setVisiblePasswords({}); setLoading(true); setRevision(value => value + 1); }}>刷新</button></div>
    {notice ? <p role="status" className="text-sm text-emerald-300">{notice}</p> : null}
    {error ? <p role="alert" className="text-sm text-red-300">{error}</p> : null}
    {loading ? <p className="text-sm text-[#bfc9e7]">正在加载...</p> : null}
    <div className="overflow-x-auto">
      <table className="w-full min-w-[760px] text-left text-sm">
        <thead className="border-b border-white/15 text-xs text-[#bfc9e7]/60"><tr>
          <th className="py-3 pr-5">账号</th><th className="py-3 pr-5">名称</th><th className="py-3 pr-5">状态</th>
          {mayView ? <th className="py-3 pr-5">当前密码</th> : null}
          <th className="py-3 pr-5">密码修改时间</th><th className="py-3 pr-5">最近登录</th>
          {mayReset ? <th className="py-3 text-right">操作</th> : null}
        </tr></thead>
        <tbody className="divide-y divide-white/10">{users.map(user => <tr key={user.id}>
          <td className="py-5 pr-5 font-bold">{user.username}{user.id === currentUserId ? <span className="ml-2 text-xs font-normal text-[#9fb0ff]">当前账号</span> : null}</td>
          <td className="py-5 pr-5 text-[#bfc9e7]">{user.display_name}</td><td className={`py-5 pr-5 ${user.is_active ? "text-emerald-300" : "text-[#bfc9e7]"}`}>{user.is_active ? "启用" : "禁用"}</td>
          {mayView ? <td className="max-w-xs py-5 pr-5">{user.has_stored_password ? <div className="space-y-2">
            {visiblePasswords[user.id] !== undefined ? <code className="block whitespace-pre-wrap break-all text-[#e0e6f5]">{visiblePasswords[user.id]}</code> : null}
            <button className="text-xs text-[#9fb0ff] underline underline-offset-4 disabled:opacity-40" disabled={reading !== null} onClick={() => reveal(user)}>{reading === user.id ? "读取中..." : visiblePasswords[user.id] !== undefined ? "隐藏密码" : "查看密码"}</button>
          </div> : <span className="text-xs text-[#bfc9e7]/55">未记录，重设后可查看</span>}</td> : null}
          <td className="py-5 pr-5 text-xs text-[#bfc9e7]">{time(user.password_changed_at)}</td><td className="py-5 pr-5 text-xs text-[#bfc9e7]">{time(user.last_login_at)}</td>
          {mayReset ? <td className="py-5 text-right">{user.username !== "admin" || operator?.username === "admin" ? <button className={control} onClick={() => open(user)}>修改密码</button> : <span className="text-xs text-[#bfc9e7]/55">仅 admin 本人可修改</span>}</td> : null}
        </tr>)}</tbody>
      </table>
    </div>
    <dialog ref={dialog} onCancel={event => { if (saving) event.preventDefault(); }} onClose={() => { setSelected(null); setPassword(""); setConfirmation(""); setFormError(""); }} className="m-auto w-[min(520px,calc(100vw-32px))] rounded-[6px] border border-[#4b5fc6] bg-[#070b1b] p-6 text-white backdrop:bg-black/70">
      <form onSubmit={save} className="space-y-5">
        <h3 className="text-lg font-bold">修改密码 · {selected?.username}</h3>
        <label className="block text-sm">新密码<input autoFocus autoComplete="new-password" required maxLength={72} type={mayView ? "text" : "password"} value={password} onChange={event => setPassword(event.target.value)} className={inputClass} /></label>
        <label className="block text-sm">确认新密码<input autoComplete="new-password" required maxLength={72} type={mayView ? "text" : "password"} value={confirmation} onChange={event => setConfirmation(event.target.value)} className={inputClass} /></label>
        <p className="text-sm text-[#bfc9e7]">{selected?.id === currentUserId ? "修改后需使用新密码重新登录。" : "修改后，该用户原有登录会话将失效。"}</p>
        {formError ? <p role="alert" className="text-sm text-red-300">{formError}</p> : null}
        <div className="flex justify-end gap-3"><button className={control} type="button" disabled={saving} onClick={() => dialog.current?.close()}>取消</button><button className={`${control} bg-[#0a1ae1]`} disabled={saving || !mayReset}>{saving ? "保存中..." : "确认修改"}</button></div>
      </form>
    </dialog>
  </section>;
}
