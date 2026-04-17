import type { Metadata } from "next";
import "./globals.css";
import { ServerHealth } from "@/components/ServerHealth";
import { Toaster } from "sonner";
import Link from "next/link";

export const metadata: Metadata = {
  title: "AuditLens — Data Compliance Agent",
  description: "AI-powered regulatory compliance scanning for transactional databases.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <header className="border-b border-ink bg-cream paper-noise">
          <div className="max-w-[1120px] mx-auto px-6 py-5 flex items-center justify-between">
            <Link href="/" className="flex items-center gap-3">
              <div className="w-9 h-9 rounded-sm bg-teal-deep flex items-center justify-center text-cream font-display text-lg">A</div>
              <div>
                <div className="font-display text-lg leading-none">AuditLens</div>
                <div className="caps-label mt-0.5">Compliance Ledger</div>
              </div>
            </Link>
            <nav className="flex items-center gap-8">
              <Link className="text-sm hover:text-teal-deep" href="/scan">Scan</Link>
              <Link className="text-sm hover:text-teal-deep" href="/">About</Link>
              <ServerHealth />
            </nav>
          </div>
          <div className="rule-double" />
        </header>
        <main className="max-w-[1120px] mx-auto px-6 py-10">{children}</main>
        <Toaster position="bottom-right" richColors />
      </body>
    </html>
  );
}
