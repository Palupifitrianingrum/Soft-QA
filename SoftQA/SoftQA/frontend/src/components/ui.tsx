import { ReactNode, useEffect, useState } from "react";
import { api } from "../api";
import type { Analysis } from "../types";

export const SEV: Record<string, string> = {
  critical: "bg-red-500/15 text-red-300 border-red-500/40", high: "bg-orange-500/15 text-orange-300 border-orange-500/40",
  medium: "bg-amber-400/15 text-amber-200 border-amber-400/40", low: "bg-sky-400/15 text-sky-300 border-sky-400/40",
  info: "bg-slate-500/15 text-slate-300 border-slate-500/40",
};
export const SEV_HEX: Record<string, string> = { critical: "#ef4444", high: "#f97316", medium: "#fbbf24", low: "#38bdf8", info: "#94a3b8" };

export const Card = ({ children, className = "" }: { children: ReactNode; className?: string }) => (
  <div className={`rounded-xl border border-slate-800 bg-slate-900/60 p-4 backdrop-blur ${className}`}>{children}</div>
);
export const SevBadge = ({ s }: { s: string }) => <span className={`rounded-md border px-2 py-0.5 text-xs font-medium uppercase ${SEV[s] ?? SEV.info}`}>{s}</span>;
export const Tag = ({ children, tone = "slate" }: { children: ReactNode; tone?: "slate" | "cyan" | "purple" | "green" | "red" }) => {
  const t = { slate: "border-slate-700 text-slate-300", cyan: "border-cyan-500/40 text-cyan-300", purple: "border-purple-500/40 text-purple-300", green: "border-emerald-500/40 text-emerald-300", red: "border-red-500/40 text-red-300" }[tone];
  return <span className={`rounded-md border px-2 py-0.5 text-xs ${t}`}>{children}</span>;
};
export const Btn = ({ children, onClick, disabled, kind = "primary", title }: { children: ReactNode; onClick?: () => void; disabled?: boolean; kind?: "primary" | "ghost"; title?: string }) => (
  <button title={title} disabled={disabled} onClick={onClick}
    className={`rounded-lg px-3 py-1.5 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-40 ${kind === "primary" ? "bg-gradient-to-r from-purple-600 to-cyan-600 text-white hover:brightness-110" : "border border-slate-700 text-slate-200 hover:bg-slate-800"}`}>{children}</button>
);
export const Notice = ({ children, tone = "amber" }: { children: ReactNode; tone?: "amber" | "red" | "cyan" }) => (
  <div className={`rounded-lg border px-3 py-2 text-sm ${{ amber: "border-amber-500/40 bg-amber-500/10 text-amber-200", red: "border-red-500/40 bg-red-500/10 text-red-200", cyan: "border-cyan-500/40 bg-cyan-500/10 text-cyan-200" }[tone]}`}>{children}</div>
);
export const Title = ({ children, right }: { children: ReactNode; right?: ReactNode }) => (
  <div className="mb-4 flex flex-wrap items-center justify-between gap-2"><h1 className="text-xl font-semibold text-white">{children}</h1>{right}</div>
);

/** Dropdown of past analyses; auto-selects the newest one when nothing is selected. */
export function AnalysisSelect({ value, onChange }: { value: number | null; onChange: (id: number) => void }) {
  const [list, setList] = useState<Analysis[]>([]);
  useEffect(() => { api.analyses().then(setList).catch(() => setList([])); }, []);
  useEffect(() => { if (value === null && list.length) onChange(list[0].id); }, [list, value, onChange]);
  if (!list.length) return <Notice tone="cyan">No analyses yet. Start one from “New Analysis”.</Notice>;
  return (
    <select value={value ?? ""} onChange={(e) => onChange(Number(e.target.value))} className="rounded-lg border border-slate-700 bg-slate-900 px-2 py-1.5 text-sm">
      {list.map((a) => <option key={a.id} value={a.id}>#{a.id} · {a.project_name} · {a.status} · {a.findings_count} findings</option>)}
    </select>
  );
}
