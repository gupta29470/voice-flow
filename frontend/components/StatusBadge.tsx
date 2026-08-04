import type { CallStatus } from "@/lib/api";

const styles: Record<CallStatus, string> = {
  initiated: "bg-sky-500/10 text-sky-400 ring-sky-500/30",
  in_progress: "bg-amber-500/10 text-amber-400 ring-amber-500/30",
  completed: "bg-emerald-500/10 text-emerald-400 ring-emerald-500/30",
  failed: "bg-rose-500/10 text-rose-400 ring-rose-500/30",
};

const labels: Record<CallStatus, string> = {
  initiated: "Initiated",
  in_progress: "In progress",
  completed: "Completed",
  failed: "Failed",
};

const dotStyles: Record<CallStatus, string> = {
  initiated: "bg-sky-400",
  in_progress: "bg-amber-400",
  completed: "bg-emerald-400",
  failed: "bg-rose-400",
};

export function StatusBadge({ status }: { status: CallStatus }) {
  const live = status === "initiated" || status === "in_progress";
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${styles[status]}`}
    >
      <span className="relative flex h-1.5 w-1.5">
        {live && (
          <span
            className={`absolute inline-flex h-full w-full animate-ping rounded-full opacity-60 ${dotStyles[status]}`}
          />
        )}
        <span className={`relative inline-flex h-1.5 w-1.5 rounded-full ${dotStyles[status]}`} />
      </span>
      {labels[status]}
    </span>
  );
}
