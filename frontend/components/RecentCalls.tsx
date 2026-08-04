"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, ApiError, workflowName, type CallSummary, type Workflow } from "@/lib/api";
import { formatDateTime, formatDuration } from "@/lib/format";
import { StatusBadge } from "@/components/StatusBadge";
import { BackendNote } from "@/components/BackendNote";
import { Skeleton } from "@/components/Skeleton";

const POLL_MS = 5000;

export function RecentCalls() {
  const [calls, setCalls] = useState<CallSummary[] | null>(null);
  const [workflowNames, setWorkflowNames] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    api
      .listWorkflows()
      .then((wf: Workflow[]) => {
        if (cancelled) return;
        setWorkflowNames(Object.fromEntries(wf.map((w) => [w.id, w.name])));
      })
      .catch(() => {
        // non-fatal — fall back to the static name map
      });

    async function load() {
      try {
        const data = await api.listCalls();
        if (cancelled) return;
        setCalls(data);
        setError(null);
      } catch (e) {
        if (cancelled) return;
        setError(e instanceof ApiError ? e.message : "Failed to load calls.");
      }
    }

    load();
    const timer = setInterval(load, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  const nameOf = (id: string) => workflowNames[id] ?? workflowName(id);

  return (
    <section className="flex min-h-0 flex-col">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-zinc-200">Recent calls</h2>
        {calls && (
          <span className="text-xs text-zinc-600">
            {calls.length} total · refreshes every 5s
          </span>
        )}
      </div>

      {error && !calls && (
        <div className="space-y-3">
          <BackendNote message={error} />
          <p className="rounded-xl border border-dashed border-white/10 p-6 text-center text-sm text-zinc-500">
            Calls will appear here once the backend is reachable.
          </p>
        </div>
      )}

      {calls === null && !error && (
        <div className="space-y-2">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-16 w-full" />
          ))}
        </div>
      )}

      {calls && calls.length === 0 && (
        <p className="rounded-xl border border-dashed border-white/10 p-6 text-center text-sm text-zinc-500">
          No calls yet — configure a workflow on the left and start your first call.
        </p>
      )}

      {calls && calls.length > 0 && (
        <ul className="space-y-2">
          {calls.map((c) => (
            <li key={c.id}>
              <Link
                href={`/calls/${c.id}`}
                className="block rounded-xl border border-white/10 bg-zinc-900/50 p-3.5 transition-colors hover:border-white/20 hover:bg-zinc-900"
              >
                <div className="flex items-center justify-between gap-3">
                  <div className="flex min-w-0 items-center gap-2.5">
                    <StatusBadge status={c.status} />
                    <span className="truncate text-sm font-medium text-zinc-100">
                      {nameOf(c.workflow_id)}
                    </span>
                  </div>
                  <span className="shrink-0 font-mono text-xs text-zinc-500">
                    {formatDateTime(c.started_at)}
                  </span>
                </div>
                <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-zinc-500">
                  <span className="font-mono text-zinc-400">{c.phone_number}</span>
                  <span className="capitalize">{c.tts_provider}</span>
                  <span>{c.voice_name}</span>
                  <span>{formatDuration(c.duration_sec)}</span>
                </div>
                {c.outcome && (
                  <p className="mt-2 truncate text-xs text-zinc-500">
                    <span className="text-zinc-600">Outcome:</span> {c.outcome}
                  </p>
                )}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
