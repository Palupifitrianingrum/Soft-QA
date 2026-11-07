import { useEffect, useState } from "react";
import { Bar, BarChart, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api";
import type { PageProps } from "../App";
import type { Stats } from "../types";
import { Card, Notice, SEV_HEX, Tag, Title } from "../components/ui";

export default function Overview({ setAnalysisId, go, status }: PageProps) {
  const [s, setS] = useState<Stats | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => { api.stats().then(setS).catch((e: Error) => setErr(e.message)); }, []);
  if (err) return <Notice tone="red">{err}</Notice>;
  if (!s) return <p className="text-slate-400">Loading…</p>;
  const cards: [string, number][] = [["Projects analyzed", s.projects], ["Bugs detected", s.bugs_detected], ["Critical/high vulnerabilities", s.critical_vulnerabilities], ["Tests executed", s.tests_executed]];
  const data = Object.entries(s.severity_distribution).map(([name, value]) => ({ name, value }));
  return (
    <>
      <Title>Overview</Title>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">{cards.map(([l, v]) => <Card key={l}><div className="text-2xl font-bold text-white">{v}</div><div className="text-xs text-slate-400">{l}</div></Card>)}</div>
      {status && (
        <div className="flex flex-wrap gap-2 text-xs">
          <Tag tone={status.ai_configured ? "green" : "red"}>AI {status.ai_configured ? status.ai_model : "off"}</Tag>
          <Tag tone={status.ruff_available ? "green" : "red"}>Ruff {status.ruff_available ? "ready" : "missing"}</Tag>
          <Tag tone={status.semgrep_available ? "green" : "red"}>Semgrep {status.semgrep_mode}</Tag>
          <Tag tone={status.docker_available ? "green" : "red"}>Sandbox {status.docker_available ? "Docker ok" : "disabled (no Docker)"}</Tag>
        </div>
      )}
      <div className="grid gap-3 lg:grid-cols-2">
        <Card>
          <h2 className="mb-2 text-sm font-semibold text-slate-300">Severity distribution (all analyses)</h2>
          <div className="h-56"><ResponsiveContainer><BarChart data={data}><XAxis dataKey="name" stroke="#64748b" fontSize={12} /><YAxis allowDecimals={false} stroke="#64748b" fontSize={12} /><Tooltip contentStyle={{ background: "#0f172a", border: "1px solid #334155" }} /><Bar dataKey="value" radius={[4, 4, 0, 0]}>{data.map((d) => <Cell key={d.name} fill={SEV_HEX[d.name]} />)}</Bar></BarChart></ResponsiveContainer></div>
        </Card>
        <Card>
          <h2 className="mb-2 text-sm font-semibold text-slate-300">Latest analyses</h2>
          {!s.recent_analyses.length && <p className="text-sm text-slate-500">Nothing yet.</p>}
          <ul className="divide-y divide-slate-800">
            {s.recent_analyses.map((a) => (
              <li key={a.id}><button className="flex w-full items-center justify-between py-2 text-left text-sm hover:text-cyan-300" onClick={() => { setAnalysisId(a.id); go("findings"); }}>
                <span>#{a.id} {a.project_name}</span><span className="text-xs text-slate-400">{a.status} · {a.findings_count} findings</span></button></li>
            ))}
          </ul>
        </Card>
      </div>
    </>
  );
}
