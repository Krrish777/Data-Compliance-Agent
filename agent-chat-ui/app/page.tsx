import Link from "next/link";

const PIPELINE_STAGES: { num: string; label: string; title: React.ReactNode; body: string; hint?: string }[] = [
  {
    num: "I",
    label: "Act the First",
    title: <>The rulebook is <em>read</em>.</>,
    body:
      "The policy PDF is parsed, chunked, and handed to an LLM that extracts machine-readable rules with confidence scores. Low-confidence rules pause the graph for human review.",
    hint: "rule_extraction → schema_discovery → rule_structuring",
  },
  {
    num: "II",
    label: "Act the Second",
    title: <>The data is <em>examined</em>.</>,
    body:
      "Schema discovery maps columns, primary keys, and sensitive PII. The scanner then walks millions of rows via keyset pagination — no OFFSET bottleneck, no memory spikes.",
    hint: "keyset pagination · SQLite · Postgres",
  },
  {
    num: "III",
    label: "Act the Third",
    title: <>A report is <em>impressed</em>.</>,
    body:
      "Each flagged record is validated by a faster LLM, then annotated in plain English with policy clauses and remediation steps. The final audit is produced as both PDF and HTML.",
    hint: "violation_validator → explanation_generator → report_generation",
  },
];

const CAPABILITIES: { num: string; title: React.ReactNode; body: string }[] = [
  {
    num: "No. I",
    title: <>Rules <em>grounded</em> in the source.</>,
    body:
      "Every extracted rule carries a citation back to the regulatory PDF — clause, page, and surrounding context. No hallucinated policy, no unverifiable claim. A rule either points to the rulebook or it does not exist.",
  },
  {
    num: "No. II",
    title: <>Scans that do not <em>choke</em> on scale.</>,
    body:
      "Keyset-paginated queries against both SQLite and Postgres. A table with forty million rows is walked in a single stream — without OFFSET, without memory spikes, without skipped segments.",
  },
  {
    num: "No. III",
    title: <>A human in the <em>loop</em>, by design.</>,
    body:
      "When a rule's confidence falls below threshold, the graph pauses with an interrupt and waits for an explicit approve, edit, or drop. Silent auto-approval is never the path of least resistance.",
  },
  {
    num: "No. IV",
    title: <>An audit artifact you can <em>hand over</em>.</>,
    body:
      "Every scan produces a PDF and an HTML report with a compliance score, violation ledger, and remediation notes. Both are written to disk and served from a stable URL — suitable for auditors, suitable for the record.",
  },
  {
    num: "No. V",
    title: <>A second graph for <em>live</em> queries.</>,
    body:
      "A separate interceptor pipeline reviews individual SQL queries pre-execution — classify intent, map policy, issue a verdict, loop an auditor on failure, escalate to a human on exhausted retries. The scanner and the interceptor share tooling and disagree respectfully.",
  },
];

export default function Home() {
  return (
    <>
      <section className="hero">
        <div className="watermark-shield" aria-hidden="true" />

        <div>
          <p className="eyebrow reveal reveal-d1">No.&nbsp;I — The Premise</p>

          <h1 className="hero-headline reveal reveal-d2">
            Your database has<br />
            compliance <em className="teal">blind spots</em>.<br />
            We find them.
          </h1>

          <p className="hero-subtitle reveal reveal-d3">
            AuditLens reads your regulatory PDFs, extracts machine-readable rules,
            and scans your SQLite or Postgres databases for violations — then
            delivers fully verified, LLM-explained audit reports in PDF and HTML.
          </p>

          <div className="hero-cta-row reveal reveal-d4">
            <Link href="/scan" className="btn btn-primary btn-lg">
              Begin Audit →
            </Link>
            <Link href="#pipeline" className="btn btn-ghost btn-lg">
              View the Pipeline
            </Link>
          </div>

          <div className="hero-meta-row reveal reveal-d5">
            <div className="hero-meta-item">
              <span className="eyebrow">Engine</span>
              <div className="hero-meta-value">LangGraph + Groq</div>
            </div>
            <div className="hero-meta-item">
              <span className="eyebrow">Models</span>
              <div className="hero-meta-value">Llama 3.3 70B · 3.1 8B</div>
            </div>
            <div className="hero-meta-item">
              <span className="eyebrow">Vector Store</span>
              <div className="hero-meta-value">Qdrant · BGE-small</div>
            </div>
          </div>
        </div>

        <aside className="hero-aside reveal reveal-d3">
          <div className="audit-seal" aria-hidden="true">
            <div className="seal-label">Sigillum Auditoris</div>
            <div className="seal-check">✓</div>
            <div className="seal-name">AuditLens</div>
            <div className="seal-year">Verified · MMXXVI</div>
          </div>

          <figure className="hero-annotation">
            <span className="eyebrow">From the Auditor — Annotation</span>
            <blockquote>
              &ldquo;The compliance gap has always been a problem of scale. We have
              made the manual audit obsolete and replaced it with a graph.&rdquo;
            </blockquote>
            <cite>— Preface, Vol. I</cite>
          </figure>
        </aside>
      </section>

      <div className="fleuron" aria-hidden="true">§ &nbsp;·&nbsp; §</div>

      <section id="pipeline" className="section">
        <div className="section-head-editorial">
          <div className="section-numeral-big" aria-hidden="true">II.</div>
          <div>
            <h2 className="section-title">
              How a scan is <em>conducted</em>.
            </h2>
            <p className="section-subtitle">
              A three-act rite: a policy is read, the data is examined, a report
              is impressed. Each act is recorded in a trace that cannot be
              rewritten.
            </p>
          </div>
        </div>

        <div className="timeline">
          {PIPELINE_STAGES.map((stage) => (
            <article key={stage.num} className="timeline-act" data-num={stage.num}>
              <span className="timeline-act-label">{stage.label}</span>
              <h3>{stage.title}</h3>
              <p>{stage.body}</p>
              {stage.hint && <div className="mono-hint">{stage.hint}</div>}
            </article>
          ))}
        </div>
      </section>

      <div className="fleuron" aria-hidden="true">§ &nbsp;·&nbsp; §</div>

      <section id="capabilities" className="section">
        <div className="section-head-editorial">
          <div className="section-numeral-big" aria-hidden="true">III.</div>
          <div>
            <h2 className="section-title">
              What it <em>does well</em>.
            </h2>
            <p className="section-subtitle">
              Five quiet guarantees the system keeps on every scan, set in the
              plainest rows we could manage.
            </p>
          </div>
        </div>

        <div className="cap-rows">
          {CAPABILITIES.map((cap) => (
            <div key={cap.num} className="cap-row">
              <div className="cap-num">{cap.num}</div>
              <div>
                <h3 className="cap-title">{cap.title}</h3>
                <p className="cap-body">{cap.body}</p>
              </div>
            </div>
          ))}
        </div>
      </section>

      <div className="fleuron" aria-hidden="true">§ &nbsp;·&nbsp; §</div>

      <section id="preview" className="section">
        <div className="section-head-editorial">
          <div className="section-numeral-big" aria-hidden="true">IV.</div>
          <div>
            <h2 className="section-title">
              The <em>artifact</em>.
            </h2>
            <p className="section-subtitle">
              Every scan leaves this behind — a compliance score, a ledger of
              violations, and a remediation note for each one. This is a
              representative fragment.
            </p>
          </div>
        </div>

        <div className="report-preview">
          <div className="report-card">
            <header className="report-header">
              <span className="report-title">Audit Report · HI-Small_Trans</span>
              <span className="report-score">
                Compliance <strong>87%</strong>
              </span>
            </header>

            <div className="report-violation">
              <span className="mono">
                Rule IV.2 · row #48,119
                <br />
                severity: high
              </span>
              <p>
                Beneficiary address missing on wire transfer of $14,200 — violates
                FinCEN travel-rule §1010.410 for amounts at or above $10,000.
              </p>
            </div>

            <div className="report-violation">
              <span className="mono">
                Rule II.7 · row #112,402
                <br />
                severity: medium
              </span>
              <p>
                Customer occupation recorded as free-text (&ldquo;works at bank&rdquo;) where the policy
                requires a code from the NAICS occupation table.
              </p>
            </div>

            <p className="report-remediation">
              — Backfill <em>address_line_1</em> from the customer KYC table; re-scan the
              flagged segment; map free-text occupations to the nearest NAICS code
              and flag ambiguous cases for review.
            </p>
          </div>
        </div>
      </section>
    </>
  );
}
