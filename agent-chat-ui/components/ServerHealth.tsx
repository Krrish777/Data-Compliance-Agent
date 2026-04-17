"use client";
import { useEffect, useState } from "react";
import { LANGGRAPH_URL } from "@/lib/langgraph";

type Health = "unknown" | "ok" | "down";

export function ServerHealth() {
  const [status, setStatus] = useState<Health>("unknown");

  useEffect(() => {
    let cancelled = false;
    const check = async () => {
      try {
        const res = await fetch(`${LANGGRAPH_URL}/ok`, { method: "GET" });
        if (!cancelled) setStatus(res.ok ? "ok" : "down");
      } catch {
        if (!cancelled) setStatus("down");
      }
    };
    check();
    const id = setInterval(check, 10_000);
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  const label =
    status === "ok"   ? "Backend online" :
    status === "down" ? "Backend offline" :
                        "Checking backend…";
  const dot =
    status === "ok"   ? "bg-accent-green" :
    status === "down" ? "bg-accent-red animate-pulse" :
                        "bg-ink-faint";

  return (
    <div className="flex items-center gap-2 text-xs text-ink-muted">
      <span className={`inline-block w-2 h-2 rounded-full ${dot}`} aria-hidden />
      {label}
    </div>
  );
}
