"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  api,
  ApiError,
  workflowName,
  type CallDetail,
  type CallMetrics,
} from "@/lib/api";
import { formatDateTime, formatDuration, formatMs, formatTimestamp } from "@/lib/format";
import { StatusBadge } from "@/components/StatusBadge";
import { BackendNote } from "@/components/BackendNote";
import { Skeleton } from "@/components/Skeleton";

const LIVE_POLL_MS = 3000;
const ERROR_RETRY_MS = 5000;

function isLive(status: string) {
  return status === "initiated" || status === "in_progress";
}

function MetricCard({
  label,
  value,
  sub,
  accent,
}: {
  label: string;
  value: string;
  sub?: string;
  accent?: boolean;
}) {
  return (
    <div
      className={`rounded-xl border p-4 ${
        accent
          ? "border-indigo-500/30 bg-indigo-500/5"
          : "border-white/10 bg-zinc-900/50"
      }`}
    >
      <p className="text-[11px] font-medium uppercase tracking-wider text-zinc-500">
        {label}
      </p>
      <p
        className={`mt-1.5 font-mono text-2xl font-semibold tracking-tight ${
          accent ? "text-indigo-300" : "text-zinc-100"
        }`}
      >
        {value}
      </p>
      {sub && <p className="mt-1 text-xs text-zinc-600">{sub}</p>}
    </div>
  );
}

function MetricsPanel({ metrics, live }: { metrics: CallMetrics | null; live: boolean }) {
  if (!metrics) {
    return (
      <div className="rounded-xl border border-dashed border-white/10 p-6 text-center">
        {live ? (
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
              {Array.from({ length: 6 }).map((_, i) => (
                <Skeleton key={i} className="h-20 w-full" />
              ))}
            </div>
            <p className="text-xs text-zinc-600">
              Latency metrics are collected as the conversation progresses…
            </p>
          </div>
        ) : (
          <p className="text-sm text-zinc-500">No metrics recorded for this call.</p>
        )}
      </div>
    );
  }

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
      <MetricCard label="End-to-end avg" value={formatMs(metrics.e2e_avg_ms)} sub="speech-to-speech" accent />
      <MetricCard label="End-to-end P95" value={formatMs(metrics.e2e_p95_ms)} sub="tail latency" accent />
      <MetricCard label="STT avg" value={formatMs(metrics.stt_avg_ms)} sub="Deepgram" />
      <MetricCard label="LLM avg" value={formatMs(metrics.llm_avg_ms)} sub="first token" />
      <MetricCard label="TTS avg" value={formatMs(metrics.tts_avg_ms)} sub="first audio byte" />
      <MetricCard label="Turns" value={String(metrics.turns)} sub="conversation turns" />
    </div>
  );
}

export default function CallDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;

  const [call, setCall] = useState<CallDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    async function load() {
      try {
        const data = await api.getCall(id);
        if (cancelled) return;
        setCall(data);
        setError(null);
        if (isLive(data.status)) {
          timer = setTimeout(load, LIVE_POLL_MS);
        }
      } catch (e) {
        if (cancelled) return;
        setError(e instanceof ApiError ? e.message : "Failed to load the call.");
        timer = setTimeout(load, ERROR_RETRY_MS);
      }
    }

    load();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [id]);

  const live = call ? isLive(call.status) : false;

  return (
    <div className="space-y-6">
      <Link
        href="/"
        className="inline-flex items-center gap-1.5 text-sm text-zinc-500 transition-colors hover:text-zinc-200"
      >
        <span aria-hidden>←</span> Back to dashboard
      </Link>

      {error && !call && (
        <div className="space-y-3">
          <BackendNote message={error} />
          <div className="space-y-3">
            <Skeleton className="h-28 w-full" />
            <Skeleton className="h-64 w-full" />
          </div>
        </div>
      )}

      {!call && !error && (
        <div className="space-y-3">
          <Skeleton className="h-28 w-full" />
          <Skeleton className="h-64 w-full" />
          <Skeleton className="h-40 w-full" />
        </div>
      )}

      {call && (
        <>
          {/* Header */}
          <div className="rounded-xl border border-white/10 bg-zinc-900/50 p-5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-3">
                <h1 className="text-lg font-semibold tracking-tight text-zinc-50">
                  {workflowName(call.workflow_id)}
                </h1>
                <StatusBadge status={call.status} />
                {live && (
                  <span className="hidden items-center gap-1.5 text-xs text-zinc-500 sm:inline-flex">
                    <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-400" />
                    Live — updating every 3s
                  </span>
                )}
              </div>
              <span className="font-mono text-xs text-zinc-600">{call.id}</span>
            </div>
            <dl className="mt-4 grid grid-cols-2 gap-x-6 gap-y-3 text-sm sm:grid-cols-3 lg:grid-cols-6">
              <div>
                <dt className="text-[11px] uppercase tracking-wider text-zinc-600">Phone</dt>
                <dd className="mt-0.5 font-mono text-zinc-200">{call.phone_number}</dd>
              </div>
              <div>
                <dt className="text-[11px] uppercase tracking-wider text-zinc-600">Provider</dt>
                <dd className="mt-0.5 capitalize text-zinc-200">{call.tts_provider}</dd>
              </div>
              <div>
                <dt className="text-[11px] uppercase tracking-wider text-zinc-600">Voice</dt>
                <dd className="mt-0.5 text-zinc-200">{call.voice_name}</dd>
              </div>
              <div>
                <dt className="text-[11px] uppercase tracking-wider text-zinc-600">Duration</dt>
                <dd className="mt-0.5 font-mono text-zinc-200">{formatDuration(call.duration_sec)}</dd>
              </div>
              <div>
                <dt className="text-[11px] uppercase tracking-wider text-zinc-600">Started</dt>
                <dd className="mt-0.5 text-zinc-200">{formatDateTime(call.started_at)}</dd>
              </div>
              <div>
                <dt className="text-[11px] uppercase tracking-wider text-zinc-600">Outcome</dt>
                <dd className="mt-0.5 text-zinc-200">{call.outcome ?? "—"}</dd>
              </div>
            </dl>
          </div>

          {/* Transcript */}
          <section>
            <h2 className="mb-3 text-sm font-semibold text-zinc-200">Transcript</h2>
            <div className="rounded-xl border border-white/10 bg-zinc-900/50 p-4 sm:p-5">
              {call.transcript.length === 0 ? (
                <p className="py-8 text-center text-sm text-zinc-500">
                  {live
                    ? "Waiting for the conversation to begin…"
                    : "No transcript recorded for this call."}
                </p>
              ) : (
                <ol className="space-y-4">
                  {call.transcript.map((turn, i) => {
                    const isAgent = turn.role === "agent";
                    return (
                      <li
                        key={i}
                        className={`flex ${isAgent ? "justify-end" : "justify-start"}`}
                      >
                        <div
                          className={`max-w-[80%] sm:max-w-[70%] ${
                            isAgent ? "text-right" : "text-left"
                          }`}
                        >
                          <p
                            className={`mb-1 text-[11px] font-medium ${
                              isAgent ? "text-indigo-400" : "text-zinc-500"
                            }`}
                          >
                            {isAgent ? "Agent" : "Caller"} ·{" "}
                            <span className="font-normal text-zinc-600">
                              {formatTimestamp(turn.timestamp)}
                            </span>
                          </p>
                          <div
                            className={`inline-block rounded-2xl px-4 py-2.5 text-sm leading-relaxed ${
                              isAgent
                                ? "rounded-tr-sm bg-indigo-500/15 text-indigo-100 ring-1 ring-indigo-500/25"
                                : "rounded-tl-sm bg-white/5 text-zinc-200 ring-1 ring-white/10"
                            }`}
                          >
                            {turn.text}
                          </div>
                        </div>
                      </li>
                    );
                  })}
                </ol>
              )}
            </div>
          </section>

          {/* Metrics */}
          <section>
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-sm font-semibold text-zinc-200">
                Latency &amp; observability
              </h2>
              <span className="text-xs text-zinc-600">
                measured per conversation turn
              </span>
            </div>
            <MetricsPanel metrics={call.metrics} live={live} />
          </section>
        </>
      )}
    </div>
  );
}
