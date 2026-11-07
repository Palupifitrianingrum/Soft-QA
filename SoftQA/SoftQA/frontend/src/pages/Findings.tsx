import { useEffect, useState } from "react";
import { api } from "../api";
import type { PageProps } from "../App";
import type { Finding } from "../types";
import { AnalysisSelect, Card, Notice, SevBadge, Tag, Title } from "../components/ui";

export function FindingCard({ f }: { f: Finding }) {
  const [open, setOpen] = useState(false);
  return (
    <Card className="cursor-pointer" >
      <div onClick={() => setOpen(!open)} className="flex flex-wrap items-center gap-2">
        <SevBadge s={f.severity} /><Tag tone={f.status === "confirmed" ? "green" : "purple"}>{f.status}</Tag><Tag>{f.category}</Tag><Tag tone="cyan">{f.source}{f.rule_id ? ` · ${f.rule_id}` : ""}</Tag>
        <span className="text-sm font-medium text-white">{f.title}</span><span className="ml-auto text-xs text-slate-400">{f.file}:{f.line_start}{f.line_end !== f.line_start ? `-${f.line_end}` : ""}</span>
      </div>
      {open && (
        <div className="mt-3 space-y-2 text-sm">
          <p className="whitespace-pre-wrap text-slate-300">{f.description}</p>
          <pre className="overflow-x-auto rounded-lg bg-slate-950 p-3 text-xs text-cyan-100">{f.evidence}</pre>
          <p><b className="text-slate-200">Recommendation:</b> <span className="text-slate-300">{f.recommendation}</span></p>
          <p className="text-xs text-slate-500">confidence {(f.confidence * 100).toFixed(0)}% · evidence {f.evidence_verified ? "matched to source" : "not verified"}{f.corroborated_by.length ? ` · corroborated by ${f.corroborated_by.join(", ")}` : ""}</p>
        </div>
      )}
    </Card>
  );
}

export default function Findings({ analysisId, setAnalysisId }: PageProps) {
  const [items, setItems] = useState<Finding[]>([]);
  const [sev, setSev] = useState(""); const [cat, setCat] = useState(""); const [err, setErr] = useState("");
  useEffect(() => { if (analysisId !== null) api.findings(analysisId).then(setItems).catch((e: Error) => setErr(e.message)); }, [analysisId]);
  const shown = items.filter((f) => (!sev || f.severity === sev) && (!cat || f.category === cat));
  const sel = "rounded-lg border border-slate-700 bg-slate-900 px-2 py-1.5 text-sm";
  return (
    <>
      <Title right={<AnalysisSelect value={analysisId} onChange={setAnalysisId} />}>Findings</Title>
      {err && <Notice tone="red">{err}</Notice>}
      <div className="flex flex-wrap gap-2">
        <select className={sel} value={sev} onChange={(e) => setSev(e.target.value)}><option value="">All severities</option>{["critical", "high", "medium", "low", "info"].map((s) => <option key={s}>{s}</option>)}</select>
        <select className={sel} value={cat} onChange={(e) => setCat(e.target.value)}><option value="">All categories</option>{["logic", "runtime", "performance", "maintainability", "security"].map((s) => <option key={s}>{s}</option>)}</select>
        <span className="self-center text-xs text-slate-400">{shown.length} of {items.length}. “potential” = AI/heuristic, not confirmed by a tool or test.</span>
      </div>
      {shown.map((f) => <FindingCard key={f.id} f={f} />)}
      {!shown.length && analysisId !== null && <p className="text-sm text-slate-500">No findings match.</p>}
    </>
  );
}
