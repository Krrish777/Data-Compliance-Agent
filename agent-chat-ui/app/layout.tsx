import type { Metadata } from "next";
import "./globals.css";
import { ServerHealth } from "@/components/ServerHealth";
import { Toaster } from "sonner";
import Link from "next/link";

export const metadata: Metadata = {
  title: "AuditLens — The Register of Data Compliance",
  description:
    "AuditLens reads your regulatory PDFs, scans your databases for violations, and emits auditable PDF/HTML reports — powered by LangGraph and Groq.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <header>
          <div className="max-w-[1120px] mx-auto px-6">
            <div className="masthead-wrap">
              <div className="masthead-inner">
                <div className="masthead-left">
                  <div className="masthead-brand-row">
                    <Link href="/" className="brand-wordmark">
                      AUDIT<span>Lens</span>
                    </Link>
                    <span className="brand-tag">Open Source · v0.1</span>
                  </div>
                  <div className="masthead-tagline">
                    — the register of data compliance, scanned in queries that leave no row unexamined —
                  </div>
                </div>
                <nav className="masthead-nav" aria-label="Primary">
                  <Link href="/#pipeline">The Pipeline</Link>
                  <Link href="/#capabilities">Capabilities</Link>
                  <Link href="/scan">Scan</Link>
                  <ServerHealth />
                </nav>
              </div>
            </div>
          </div>
        </header>

        <main className="max-w-[1120px] mx-auto px-6">{children}</main>

        <footer className="colophon-wrap">
          <div className="colophon-inner">
            <div>
              <span className="colophon-mark">Colophon · MMXXVI</span>
              <p className="colophon-primary">
                AuditLens is an open-source compliance agent. It reads the rulebook,
                examines the ledger, and leaves a trace that cannot be rewritten.
              </p>
              <div className="colophon-meta">
                LangGraph · Groq · Qdrant · Next.js
              </div>
            </div>

            <div className="colophon-col">
              <h4>Navigate</h4>
              <ul>
                <li><Link href="/">Home</Link></li>
                <li><Link href="/#pipeline">The Pipeline</Link></li>
                <li><Link href="/#capabilities">Capabilities</Link></li>
                <li><Link href="/scan">Begin a Scan</Link></li>
              </ul>
            </div>

            <div className="colophon-col">
              <h4>Source</h4>
              <ul>
                <li>
                  <a
                    href="https://github.com/Krrish777/Data-Compliance-Agent"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    GitHub Repository
                  </a>
                </li>
                <li>
                  <a
                    href="https://github.com/Krrish777/Data-Compliance-Agent#readme"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    Documentation
                  </a>
                </li>
                <li>
                  <a
                    href="https://github.com/Krrish777/Data-Compliance-Agent/issues"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    Report an Issue
                  </a>
                </li>
              </ul>
            </div>
          </div>
        </footer>

        <Toaster position="bottom-right" richColors />
      </body>
    </html>
  );
}
