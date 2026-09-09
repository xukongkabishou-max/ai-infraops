export type PasswordExpiry = {
  state: "unknown" | "never" | "scheduled" | "expired";
  expires_at: string | null;
  lifetime_seconds: number | null;
  source: string;
};

export function passwordExpiryText(expiry?: PasswordExpiry): string {
  if (!expiry) return "未知（未读取密码策略）";
  if (expiry.expires_at) return new Date(expiry.expires_at).toLocaleString("zh-CN", { hour12: false });
  if (expiry.state === "expired") return "密码已过期（时间未提供）";
  if (expiry.state === "never") return "永不过期";
  if (expiry.lifetime_seconds && expiry.lifetime_seconds > 0) {
    const days = expiry.lifetime_seconds / 86400;
    return `有效期 ${Number.isInteger(days) ? `${days} 天` : `${expiry.lifetime_seconds} 秒`}（起算时间未知）`;
  }
  return "未知（未读取密码策略）";
}
