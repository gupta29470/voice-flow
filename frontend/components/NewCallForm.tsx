"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  api,
  ApiError,
  type TtsProvider,
  type Voice,
  type Workflow,
} from "@/lib/api";
import { BackendNote } from "@/components/BackendNote";
import { CardSkeleton, Skeleton } from "@/components/Skeleton";

const inputClass =
  "w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-zinc-100 placeholder:text-zinc-600 transition-colors focus:border-indigo-500/60 focus:bg-white/[0.07] focus:outline-none";

const labelClass = "mb-1.5 block text-xs font-medium text-zinc-400";

const PROVIDERS: { id: TtsProvider; name: string; blurb: string }[] = [
  { id: "cartesia", name: "Cartesia", blurb: "Sonic — ultra-low latency" },
  { id: "elevenlabs", name: "ElevenLabs", blurb: "Premium voice quality" },
];

export function NewCallForm() {
  const [workflows, setWorkflows] = useState<Workflow[] | null>(null);
  const [voices, setVoices] = useState<Voice[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [workflowId, setWorkflowId] = useState<string | null>(null);
  const [fieldValues, setFieldValues] = useState<Record<string, string>>({});
  const [phone, setPhone] = useState("");
  const [language, setLanguage] = useState("en");
  const [provider, setProvider] = useState<TtsProvider>("cartesia");
  const [voiceId, setVoiceId] = useState<string>("");

  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [createdCallId, setCreatedCallId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([api.listWorkflows(), api.listVoices()])
      .then(([wf, vc]) => {
        if (cancelled) return;
        setWorkflows(wf);
        setVoices(vc);
        const first = vc.find((v) => v.provider === "cartesia");
        if (first) setVoiceId(first.id);
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setLoadError(e instanceof ApiError ? e.message : "Failed to load configuration.");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const workflow = useMemo(
    () => workflows?.find((w) => w.id === workflowId) ?? null,
    [workflows, workflowId]
  );

  const providerVoices = useMemo(
    () => voices?.filter((v) => v.provider === provider) ?? [],
    [voices, provider]
  );

  const selectedVoice = useMemo(
    () => providerVoices.find((v) => v.id === voiceId) ?? null,
    [providerVoices, voiceId]
  );

  function selectWorkflow(id: string) {
    setWorkflowId(id);
    setFieldValues({});
    setCreatedCallId(null);
  }

  function selectProvider(p: TtsProvider) {
    setProvider(p);
    const first = voices?.find((v) => v.provider === p);
    setVoiceId(first?.id ?? "");
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!workflow || !voiceId || !phone.trim()) return;
    setSubmitting(true);
    setSubmitError(null);
    setCreatedCallId(null);
    try {
      const context: Record<string, string> = {};
      for (const f of workflow.fields) {
        const v = fieldValues[f.key]?.trim();
        if (v) context[f.key] = v;
      }
      const res = await api.createCall({
        workflow_id: workflow.id,
        phone_number: phone.trim(),
        tts_provider: provider,
        voice_id: voiceId,
        language,
        context,
      });
      setCreatedCallId(res.call_id);
    } catch (err) {
      setSubmitError(
        err instanceof ApiError ? err.message : "Failed to start the call. Please try again."
      );
    } finally {
      setSubmitting(false);
    }
  }

  const canSubmit =
    !!workflow &&
    !!voiceId &&
    phone.trim().length > 0 &&
    workflow.fields.every((f) => !f.required || fieldValues[f.key]?.trim()) &&
    !submitting;

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      {loadError && <BackendNote message={loadError} />}

      {/* 1 — Category */}
      <section>
        <h2 className="mb-3 text-sm font-semibold text-zinc-200">
          1 · Choose a workflow
        </h2>
        {workflows === null && !loadError ? (
          <div className="grid gap-3 sm:grid-cols-2">
            {Array.from({ length: 4 }).map((_, i) => (
              <CardSkeleton key={i} lines={2} />
            ))}
          </div>
        ) : workflows && workflows.length > 0 ? (
          <div className="grid gap-3 sm:grid-cols-2">
            {workflows.map((w) => {
              const active = w.id === workflowId;
              return (
                <button
                  key={w.id}
                  type="button"
                  onClick={() => selectWorkflow(w.id)}
                  className={`rounded-xl border p-4 text-left transition-all ${
                    active
                      ? "border-indigo-500/60 bg-indigo-500/10 ring-1 ring-indigo-500/40"
                      : "border-white/10 bg-zinc-900/50 hover:border-white/20 hover:bg-zinc-900"
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm font-medium text-zinc-100">{w.name}</span>
                    <span
                      className={`h-2 w-2 shrink-0 rounded-full ${
                        active ? "bg-indigo-400" : "bg-zinc-700"
                      }`}
                    />
                  </div>
                  <p className="mt-1 line-clamp-2 text-xs leading-relaxed text-zinc-500">
                    {w.description}
                  </p>
                </button>
              );
            })}
          </div>
        ) : (
          <p className="rounded-xl border border-dashed border-white/10 p-4 text-sm text-zinc-500">
            No workflows available.
          </p>
        )}
      </section>

      {/* 2 — Dynamic context fields */}
      {workflow && (
        <section>
          <h2 className="mb-3 text-sm font-semibold text-zinc-200">
            2 · Call context — {workflow.name}
          </h2>
          <div className="grid gap-4 rounded-xl border border-white/10 bg-zinc-900/50 p-4 sm:grid-cols-2">
            {workflow.fields.map((f) => (
              <div key={f.key} className={f.type === "text" ? "sm:col-span-2" : ""}>
                <label htmlFor={`field-${f.key}`} className={labelClass}>
                  {f.label}
                  {f.required && <span className="ml-0.5 text-indigo-400">*</span>}
                </label>
                <input
                  id={`field-${f.key}`}
                  type={f.type}
                  required={f.required}
                  placeholder={f.placeholder}
                  value={fieldValues[f.key] ?? ""}
                  onChange={(e) =>
                    setFieldValues((prev) => ({ ...prev, [f.key]: e.target.value }))
                  }
                  className={inputClass}
                />
              </div>
            ))}
            {workflow.fields.length === 0 && (
              <p className="text-sm text-zinc-500 sm:col-span-2">
                This workflow needs no extra context.
              </p>
            )}
          </div>
        </section>
      )}

      {/* 3 — Phone number & language */}
      <section>
        <h2 className="mb-3 text-sm font-semibold text-zinc-200">3 · Phone &amp; language</h2>
        <div className="space-y-4 rounded-xl border border-white/10 bg-zinc-900/50 p-4">
          <div>
            <label htmlFor="phone" className={labelClass}>
              Recipient number (E.164) <span className="ml-0.5 text-indigo-400">*</span>
            </label>
            <input
              id="phone"
              type="tel"
              required
              placeholder="+14155552671"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              className={`${inputClass} font-mono`}
            />
            <p className="mt-2 text-xs text-zinc-600">
              Include country code, e.g. +1… or +91…. Twilio trial accounts can only call
              verified numbers.
            </p>
          </div>
          <div>
            <label htmlFor="language" className={labelClass}>
              Call language
            </label>
            <select
              id="language"
              value={language}
              onChange={(e) => setLanguage(e.target.value)}
              className={`${inputClass} appearance-none`}
            >
              <option value="en" className="bg-zinc-900">English</option>
              <option value="hi" className="bg-zinc-900">Hindi</option>
              <option value="hinglish" className="bg-zinc-900">Hinglish</option>
            </select>
          </div>
        </div>
      </section>

      {/* 4 — Voice */}
      <section>
        <h2 className="mb-3 text-sm font-semibold text-zinc-200">4 · Agent voice</h2>
        <div className="space-y-4 rounded-xl border border-white/10 bg-zinc-900/50 p-4">
          <div className="grid grid-cols-2 gap-2 rounded-lg bg-black/40 p-1">
            {PROVIDERS.map((p) => {
              const active = p.id === provider;
              return (
                <button
                  key={p.id}
                  type="button"
                  onClick={() => selectProvider(p.id)}
                  className={`rounded-md px-3 py-2 text-left transition-colors ${
                    active ? "bg-zinc-800 ring-1 ring-white/10" : "hover:bg-white/5"
                  }`}
                >
                  <span
                    className={`block text-sm font-medium ${
                      active ? "text-zinc-100" : "text-zinc-400"
                    }`}
                  >
                    {p.name}
                  </span>
                  <span className="block text-[11px] text-zinc-600">{p.blurb}</span>
                </button>
              );
            })}
          </div>

          {voices === null && !loadError ? (
            <Skeleton className="h-9 w-full" />
          ) : providerVoices.length > 0 ? (
            <div>
              <label htmlFor="voice" className={labelClass}>
                Voice
              </label>
              <select
                id="voice"
                value={voiceId}
                onChange={(e) => setVoiceId(e.target.value)}
                className={`${inputClass} appearance-none`}
              >
                {providerVoices.map((v) => (
                  <option key={v.id} value={v.id} className="bg-zinc-900">
                    {v.name}
                  </option>
                ))}
              </select>
              {selectedVoice && (
                <p className="mt-2 text-xs text-zinc-500">{selectedVoice.description}</p>
              )}
            </div>
          ) : (
            <p className="text-sm text-zinc-500">
              No voices available for this provider.
            </p>
          )}
        </div>
      </section>

      {/* Submit */}
      <div className="space-y-3">
        {submitError && (
          <div className="rounded-lg border border-rose-500/20 bg-rose-500/5 px-3 py-2.5 text-xs text-rose-300">
            {submitError}
          </div>
        )}
        {createdCallId && (
          <div className="flex items-center justify-between gap-3 rounded-lg border border-emerald-500/20 bg-emerald-500/5 px-3 py-2.5 text-xs text-emerald-300">
            <span>
              Call initiated — the agent is dialing now.{" "}
              <span className="font-mono text-emerald-400/80">{createdCallId}</span>
            </span>
            <Link
              href={`/calls/${createdCallId}`}
              className="shrink-0 rounded-md bg-emerald-500/15 px-2.5 py-1 font-medium text-emerald-300 ring-1 ring-emerald-500/30 transition-colors hover:bg-emerald-500/25"
            >
              View live →
            </Link>
          </div>
        )}
        <button
          type="submit"
          disabled={!canSubmit}
          className="w-full rounded-xl bg-indigo-500 px-4 py-3 text-sm font-semibold text-white shadow-lg shadow-indigo-500/20 transition-all hover:bg-indigo-400 disabled:cursor-not-allowed disabled:opacity-40 disabled:shadow-none"
        >
          {submitting ? (
            <span className="inline-flex items-center gap-2">
              <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />
              Placing call…
            </span>
          ) : (
            "Start Call"
          )}
        </button>
      </div>
    </form>
  );
}
