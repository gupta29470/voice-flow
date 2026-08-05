// Typed API client for the VoiceFlow FastAPI backend.

export const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ---------------------------------------------------------------------------
// Types (mirror the backend schemas)
// ---------------------------------------------------------------------------

export type TtsProvider = "cartesia" | "elevenlabs";

export type WorkflowFieldType = "text" | "number" | "date" | "tel";

export interface WorkflowField {
  key: string;
  label: string;
  type: WorkflowFieldType;
  required: boolean;
  placeholder?: string;
}

export interface Workflow {
  id: string;
  name: string;
  description: string;
  fields: WorkflowField[];
}

export interface Voice {
  provider: TtsProvider;
  id: string;
  name: string;
  description: string;
}

export type CallStatus = "initiated" | "in_progress" | "completed" | "failed";

export interface CallSummary {
  id: string;
  workflow_id: string;
  phone_number: string;
  status: CallStatus;
  outcome: string | null;
  tts_provider: string;
  voice_name: string;
  started_at: string; // ISO 8601
  duration_sec: number | null;
}

export interface TranscriptTurn {
  role: "agent" | "caller";
  text: string;
  timestamp: string;
}

export interface CallMetrics {
  turns: number;
  stt_avg_ms: number;
  llm_avg_ms: number;
  tts_avg_ms: number;
  e2e_avg_ms: number;
  e2e_p95_ms: number;
}

export interface CallDetail extends CallSummary {
  transcript: TranscriptTurn[];
  metrics: CallMetrics | null;
}

export interface CreateCallRequest {
  workflow_id: string;
  phone_number: string;
  tts_provider: TtsProvider;
  voice_id: string;
  language?: string;
  context: Record<string, string>;
}

export interface CreateCallResponse {
  call_id: string;
  status: "initiated";
}

// ---------------------------------------------------------------------------
// Fetch wrapper
// ---------------------------------------------------------------------------

export class ApiError extends Error {
  /** true when the backend could not be reached at all (network failure). */
  readonly unreachable: boolean;
  readonly status?: number;

  constructor(message: string, opts: { unreachable?: boolean; status?: number } = {}) {
    super(message);
    this.name = "ApiError";
    this.unreachable = opts.unreachable ?? false;
    this.status = opts.status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      cache: "no-store",
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...init?.headers,
      },
    });
  } catch {
    throw new ApiError(`Could not reach the VoiceFlow backend at ${API_URL}`, {
      unreachable: true,
    });
  }

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") detail = body.detail;
      else if (Array.isArray(body?.detail)) detail = JSON.stringify(body.detail);
    } catch {
      // non-JSON error body — keep statusText
    }
    throw new ApiError(detail, { status: res.status });
  }

  return (await res.json()) as T;
}

// ---------------------------------------------------------------------------
// Endpoints
// ---------------------------------------------------------------------------

export const api = {
  listWorkflows: () =>
    request<{ workflows: Workflow[] }>("/api/workflows").then((r) => r.workflows),

  listVoices: () => request<{ voices: Voice[] }>("/api/voices").then((r) => r.voices),

  getAppConfig: () => request<{ app_active: boolean }>("/api/config"),

  createCall: (body: CreateCallRequest) =>
    request<CreateCallResponse>("/api/calls", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  listCalls: () => request<{ calls: CallSummary[] }>("/api/calls").then((r) => r.calls),

  getCall: (id: string) => request<CallDetail>(`/api/calls/${encodeURIComponent(id)}`),
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Fallback display names for known workflow ids (used when /api/workflows is unavailable). */
const WORKFLOW_NAME_FALLBACK: Record<string, string> = {
  loan_recovery: "Loan Recovery",
  emi_reminder: "EMI Reminder",
  banking_info: "Banking Info",
  sales: "Sales",
};

export function workflowName(id: string): string {
  return WORKFLOW_NAME_FALLBACK[id] ?? id;
}
