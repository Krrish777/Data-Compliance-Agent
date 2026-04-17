"use client";
import { RadialBarChart, RadialBar, PolarAngleAxis, ResponsiveContainer } from "recharts";

export function ScoreGauge({ score, grade }: { score: number; grade: string }) {
  const color =
    score >= 85 ? "var(--accent-green)" :
    score >= 70 ? "var(--teal-deep)" :
    score >= 50 ? "var(--accent-amber)" :
                  "var(--accent-red)";

  return (
    <div className="bg-card border border-border p-6 rounded-sm flex flex-col items-center">
      <div className="caps-label mb-2">Compliance Score</div>
      <div className="relative w-56 h-56">
        <ResponsiveContainer width="100%" height="100%">
          <RadialBarChart
            innerRadius="80%"
            outerRadius="100%"
            data={[{ value: score, fill: color }]}
            startAngle={90}
            endAngle={-270}
          >
            <PolarAngleAxis type="number" domain={[0, 100]} angleAxisId={0} tick={false} />
            <RadialBar background dataKey="value" cornerRadius={6} />
          </RadialBarChart>
        </ResponsiveContainer>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <div className="font-display text-6xl text-ink">{score}</div>
          <div className="caps-label mt-1">Grade {grade}</div>
        </div>
      </div>
    </div>
  );
}
