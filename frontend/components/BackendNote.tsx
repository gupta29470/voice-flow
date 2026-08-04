import { API_URL } from "@/lib/api";

export function BackendNote({ message }: { message?: string }) {
  return (
    <div className="rounded-lg border border-amber-500/20 bg-amber-500/5 px-3 py-2.5 text-xs text-amber-300/90">
      <span className="font-medium text-amber-300">Backend offline?</span>{" "}
      {message ?? `Could not reach the API at ${API_URL}. Make sure the FastAPI server is running.`}
    </div>
  );
}
