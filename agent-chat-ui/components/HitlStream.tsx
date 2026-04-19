"use client";

import { useState } from "react";
import type { LowConfidenceRule, HitlDecision } from "./HitlModal";

export type { LowConfidenceRule, HitlDecision };

type Selection = "approve" | "drop";

export function HitlStream({
  rules,
  message,
  onResume,
}: {
  rules: LowConfidenceRule[];
  message: string;
  onResume: (decision: HitlDecision) => void;
}) {
  const [selections, setSelections] = useState<Record<string, Selection>>(() =>
    Object.fromEntries(rules.map((r) => [r.rule_id, "approve" as const])),
  );
  const [submitted, setSubmitted] = useState(false);

  const setDecision = (ruleId: string, value: Selection) => {
    setSelections((prev) => ({ ...prev, [ruleId]: value }));
  };

  const submit = () => {
    if (submitted) return;
    const approved: string[] = [];
    const dropped: string[] = [];
    for (const r of rules) {
      if (selections[r.rule_id] === "drop") dropped.push(r.rule_id);
      else approved.push(r.rule_id);
    }
    setSubmitted(true);
    onResume({ approved, edited: [], dropped });
  };

  const approvedCount = Object.values(selections).filter((v) => v === "approve").length;
  const droppedCount = rules.length - approvedCount;

  return (
    <article className="hitl-msg">
      <div className="stage-msg-marker">
        <div className="stage-msg-numeral" aria-hidden>IV</div>
        <div className="stage-msg-dot" aria-hidden />
      </div>

      <div className="hitl-card">
        <header className="hitl-card-head">
          <h3 className="hitl-card-title">
            Your <em>signature</em> is requested.
          </h3>
          <span className="hitl-card-meta">
            {rules.length} rule{rules.length === 1 ? "" : "s"} · low confidence
          </span>
        </header>

        <p className="hitl-card-intro">{message}</p>

        <div>
          {rules.map((r) => {
            const choice = selections[r.rule_id];
            return (
              <div key={r.rule_id} className="hitl-rule">
                <div>
                  <div className="hitl-rule-meta">
                    <span className="hitl-rule-id">{r.rule_id}</span>
                    <span className="hitl-rule-type">{r.rule_type}</span>
                    <span className="hitl-rule-conf">
                      confidence {(r.confidence * 100).toFixed(0)}%
                    </span>
                  </div>
                  <p className="hitl-rule-text">{r.rule_text}</p>
                  <div className="hitl-rule-expr">
                    {r.target_column} <strong>{r.operator}</strong> {String(r.value)}
                  </div>
                </div>

                <div className="hitl-rule-actions" role="radiogroup" aria-label={`Decision for ${r.rule_id}`}>
                  <button
                    type="button"
                    role="radio"
                    aria-checked={choice === "approve"}
                    className={`hitl-action approve${choice === "approve" ? " is-selected" : ""}`}
                    onClick={() => setDecision(r.rule_id, "approve")}
                    disabled={submitted}
                  >
                    Approve
                  </button>
                  <button
                    type="button"
                    role="radio"
                    aria-checked={choice === "drop"}
                    className={`hitl-action drop${choice === "drop" ? " is-selected" : ""}`}
                    onClick={() => setDecision(r.rule_id, "drop")}
                    disabled={submitted}
                  >
                    Drop
                  </button>
                </div>
              </div>
            );
          })}
        </div>

        <footer className="hitl-card-foot">
          <span className="hitl-card-foot-note">
            {approvedCount} approved · {droppedCount} dropped — resume when ready.
          </span>
          <button
            type="button"
            className="hitl-resume"
            onClick={submit}
            disabled={submitted}
          >
            {submitted ? "Resuming…" : "Submit & Resume Audit →"}
          </button>
        </footer>
      </div>
    </article>
  );
}
