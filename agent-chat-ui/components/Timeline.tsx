"use client";
import { PIPELINE_STAGES, type StageId } from "@/lib/langgraph";
import { Check, Loader2, Circle, AlertCircle } from "lucide-react";

export type StageStatus = "pending" | "running" | "done" | "error" | "waiting";

export function Timeline({
  stageStatus,
}: {
  stageStatus: Record<StageId, StageStatus>;
}) {
  return (
    <ol className="relative border-l border-border-dark ml-3">
      {PIPELINE_STAGES.map((stage, idx) => {
        const s = stageStatus[stage.id] || "pending";
        const iconWrap =
          s === "done"    ? "bg-accent-green text-white border-accent-green" :
          s === "running" ? "bg-teal-deep text-white border-teal-deep animate-pulse" :
          s === "error"   ? "bg-accent-red text-white border-accent-red" :
          s === "waiting" ? "bg-accent-amber text-white border-accent-amber animate-pulse" :
                            "bg-cream text-ink-faint border-border-dark";
        const Icon =
          s === "done"    ? Check :
          s === "running" ? Loader2 :
          s === "error"   ? AlertCircle :
          s === "waiting" ? AlertCircle :
                            Circle;
        return (
          <li key={stage.id} className="mb-6 ml-5">
            <span
              className={`absolute -left-[13px] flex items-center justify-center w-6 h-6 rounded-full border ${iconWrap}`}
            >
              <Icon className={`w-3.5 h-3.5 ${s === "running" ? "animate-spin" : ""}`} />
            </span>
            <div className="flex items-baseline gap-3">
              <span className="caps-label text-[10px]">Stage {roman(idx + 1)}</span>
              <span className="font-display text-lg">{stage.label}</span>
            </div>
            <div className="text-sm text-ink-muted mt-0.5">{stage.hint}</div>
          </li>
        );
      })}
    </ol>
  );
}

function roman(n: number): string {
  const map: [number, string][] = [
    [10, "X"], [9, "IX"], [5, "V"], [4, "IV"], [1, "I"],
  ];
  let out = "";
  for (const [v, s] of map) {
    while (n >= v) { out += s; n -= v; }
  }
  return out;
}
