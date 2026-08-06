export function formatDuration(sec: number | null): string {
  if (sec == null) return "—";
  const total = Math.round(sec);
  const m = Math.floor(total / 60);
  const s = total % 60;
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

export function formatDateTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatTimestamp(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function formatMs(ms: number | null | undefined): string {
  if (ms == null || Number.isNaN(ms)) return "—";
  if (ms >= 1000) return `${(ms / 1000).toFixed(2)}s`;
  return `${Math.round(ms)}ms`;
}

/** Mask a phone for display, e.g. +14155552671 → +1••••••••71 */
export function maskPhone(phone: string | null | undefined): string {
  const raw = (phone ?? "").trim();
  if (!raw) return "—";
  const digits = raw.replace(/\D/g, "");
  if (digits.length === 0) return "••••";
  if (digits.length <= 4) return "•".repeat(digits.length);
  const prefix = raw.startsWith("+") ? "+" : "";
  const keepStart = digits.length >= 11 ? 2 : 1;
  const start = digits.slice(0, keepStart);
  const end = digits.slice(-2);
  const maskedLen = Math.max(digits.length - keepStart - 2, 4);
  return `${prefix}${start}${"•".repeat(maskedLen)}${end}`;
}

export function looksLikePhone(value: string): boolean {
  const t = value.trim();
  if (!t) return false;
  const digits = t.replace(/\D/g, "");
  return digits.length >= 8 && /^\+?[\d\s().-]+$/.test(t);
}

export function isPhoneFieldKey(key: string): boolean {
  return /phone|mobile|tel|msisdn/i.test(key);
}
