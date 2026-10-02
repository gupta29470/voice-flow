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

/**
 * Field keys that carry a phone number: `phone`, `PHONE_NUMBER`, `tel_no`, `callerPhone`,
 * `phoneNumber`, `homeTel`.
 *
 * A phone token has to be a WHOLE SEGMENT — the key, or a piece of it between separators or
 * camelCase humps. The loose substring match this replaces tested `phone|mobile|tel|msisdn`
 * anywhere in the key, so `hotel` and `telemetry` were phone fields and their values got masked:
 * a reader cannot tell which field was mangled or why, and a half-masked hotel name is worse than
 * an unmasked one.
 *
 * Three patterns, because the boundaries are not one thing and `i` cannot be added to all of them:
 * under `i` a `[A-Z]` is no longer "a capital letter", which is exactly the distinction separating
 * `phoneNumber` from `telemetry`. `telephone` is its own token for the same reason — it IS a phone
 * field, and `tel` + `e` is where it and `telemetry` part company.
 */
const PHONE_KEY_SEPARATED = /(?:^|[_.\s-])(?:phone|telephone|mobile|msisdn|tel)(?=[_.\s-]|$)/i;
const PHONE_KEY_CAMEL = /(?:[a-z0-9])(?:Phone|Telephone|Mobile|Msisdn|Tel)(?=[A-Z]|$)/;
const PHONE_KEY_LEADING = /^(?:phone|telephone|mobile|msisdn|tel)(?=[A-Z])/;

export function isPhoneFieldKey(key: string): boolean {
  return (
    PHONE_KEY_SEPARATED.test(key) || PHONE_KEY_CAMEL.test(key) || PHONE_KEY_LEADING.test(key)
  );
}
