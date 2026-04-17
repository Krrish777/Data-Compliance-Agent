"use client";
import { useState } from "react";

export type LowConfidenceRule = {
  rule_id: string;
  rule_text: string;
  target_column: string;
  operator: string;
  value: string;
  confidence: number;
  rule_type: string;
};

export type HitlDecision = {
  approved: string[];
  edited: { rule_id: string; changes: Record<string, unknown> }[];
  dropped: string[];
};

export function HitlModal({
  rules,
  message,
  onResume,
}: {
  rules: LowConfidenceRule[];
  message: string;
  onResume: (decision: HitlDecision) => void;
}) {
  const [selections, setSelections] = useState<Record<string, "approve" | "drop">>(
    Object.fromEntries(rules.map((r) => [r.rule_id, "approve" as const])),
  );

  const submit = () => {
    const approved: string[] = [];
    const dropped: string[] = [];
    for (const r of rules) {
      if (selections[r.rule_id] === "drop") dropped.push(r.rule_id);
      else approved.push(r.rule_id);
    }
    onResume({ approved, edited: [], dropped });
  };

  return (
    <div className="fixed inset-0 z-50 bg-ink/60 flex items-center justify-center p-6">
      <div className="bg-cream max-w-3xl w-full max-h-[85vh] overflow-y-auto border border-ink rounded-sm">
        <div className="p-6 border-b border-border">
          <div className="caps-label mb-2">Human-in-the-loop · Pause</div>
          <h2 className="display-lg text-2xl">Your decision is required</h2>
          <p className="text-sm text-ink-secondary mt-2">{message}</p>
        </div>

        <div className="p-6 space-y-4">
          {rules.map((r) => (
            <div key={r.rule_id} className="bg-card border border-border p-4 rounded-sm">
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1">
                  <div className="flex items-center gap-3">
                    <span className="font-mono text-xs bg-teal-wash text-teal-deep px-2 py-0.5 rounded-sm">
                      {r.rule_id}
                    </span>
                    <span className="caps-label">{r.rule_type}</span>
                    <span className="text-xs text-ink-muted">
                      confidence {(r.confidence * 100).toFixed(0)}%
                    </span>
                  </div>
                  <div className="mt-2 text-sm">{r.rule_text}</div>
                  <div className="mt-1 font-mono text-xs text-ink-muted">
                    {r.target_column} <span className="text-teal-deep">{r.operator}</span> {String(r.value)}
                  </div>
                </div>
                <div className="flex flex-col gap-1 text-xs shrink-0">
                  <label className="flex items-center gap-1 cursor-pointer">
                    <input
                      type="radio"
                      name={r.rule_id}
                      checked={selections[r.rule_id] === "approve"}
                      onChange={() => setSelections((s) => ({ ...s, [r.rule_id]: "approve" }))}
                    />
                    Approve
                  </label>
                  <label className="flex items-center gap-1 cursor-pointer">
                    <input
                      type="radio"
                      name={r.rule_id}
                      checked={selections[r.rule_id] === "drop"}
                      onChange={() => setSelections((s) => ({ ...s, [r.rule_id]: "drop" }))}
                    />
                    Drop
                  </label>
                </div>
              </div>
            </div>
          ))}
        </div>

        <div className="p-6 border-t border-border flex items-center justify-between">
          <div className="text-xs text-ink-muted">
            {rules.length} rule{rules.length === 1 ? "" : "s"} awaiting decision
          </div>
          <button
            className="bg-teal-deep text-cream px-6 py-2.5 rounded-sm text-sm tracking-wider uppercase hover:bg-teal-mid"
            onClick={submit}
          >
            Submit & Resume →
          </button>
        </div>
      </div>
    </div>
  );
}
