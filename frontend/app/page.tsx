import { NewCallForm } from "@/components/NewCallForm";
import { RecentCalls } from "@/components/RecentCalls";

export default function Home() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight text-zinc-50">
          New Call
        </h1>
        <p className="mt-1 text-sm text-zinc-500">
          Configure an AI voice agent and place a live outbound call.
        </p>
      </div>
      <div className="grid gap-10 lg:grid-cols-2 lg:gap-8">
        <NewCallForm />
        <div className="lg:border-l lg:border-white/5 lg:pl-8">
          <RecentCalls />
        </div>
      </div>
    </div>
  );
}
