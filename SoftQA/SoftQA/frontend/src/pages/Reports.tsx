import { useEffect, useState } from "react";
import { api } from "../api";
import type { PageProps } from "../App";
import type { Report } from "../types";
import { AnalysisSelect, Card, Notice, SevBadge, Tag, Title } from "../components/ui";

export default function Reports({ analysisId, setAnalysisId }: PageProps) {
  const [r, setR] = useState<Report | null>(null); const [err, setErr] = useState("");
  useEffect(() => { if (analysisId !== null) { setErr(""); api.report(analysisId).then(setR).catch((e: Error) => setErr(e.message)); } }, [analysisId]);
  const ex = r?.tests.latest_execution;
  return (
    <>
      <Title right={<AnalysisSelect value={analysisId} onChange={setAnalysisId} />}>Reports</Title>
      {err && <Notice tone="red">{err}</Notice>}
      {r && (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <a className="rounded-lg bg-gradient-to-r from-purple-600 to-cyan-600 px-3 py-1.5 text-sm text-white" href={api.exportUrl(r.analysis_id, "pdf")}>Export PDF</a>
            <a className="rounded-lg border border-slate-700 px-3 py-1.5 text-sm" href={api.exportUrl(r.analysis_id, "json")}>Export JSON</a>
            <span className="text-xs text-slate-400">generated {new Date(r.generated_at).toLocaleString()}</span>
          </div>
          <Card className="space-y-2 text-sm">
            <h2 className="font-semibold text-white">{r.project.name}</h2>
            <p>{r.summary}</p>
            <div className="flex flex-wrap gap-2"><Tag>{r.overview.files_total} files ({r.overview.python_files} Python)</Tag><Tag>{r.overview.total_lines} lines</Tag><Tag tone="green">{r.confirmed_count} confirmed</Tag><Tag tone="purple">{r.potential_count} potential</Tag><Tag tone={r.ai_used ? "cyan" : "red"}>AI {r.ai_used ? "used" : "not used"}</Tag></div>
            <div className="flex flex-wrap gap-2">{Object.entries(r.severity_distribution).map(([k, v]) => <span key={k} className="flex items-center gap-1"><SevBadge s={k} />{v}</span>)}</div>
            <p className="text-xs text-slate-400">Quality score {r.quality.score}/100. {r.quality.note}</p>
          </Card>
          <Card className="space-y-1 text-sm">
            <h2 className="font-semibold text-white">Tests</h2>
            <p>{r.tests.generated} generated · {r.tests.approved} approved · {r.tests.rejected_by_validation} rejected by validation</p>
            <p className="text-slate-300">{ex ? `Last run: ${ex.passed} passed, ${ex.failed} failed, ${ex.errors} errors, coverage ${ex.coverage_percent === null ? "n/a" : ex.coverage_percent.toFixed(1) + "%"}` : "No execution yet."}</p>
          </Card>
          <Card className="space-y-1 text-sm"><h2 className="font-semibold text-white">Recommendations</h2><ul className="list-disc pl-5 text-slate-300">{r.recommendations.map((x, i) => <li key={i}>{x}</li>)}</ul></Card>
          {r.warnings.length > 0 && <Card className="space-y-2"><h2 className="text-sm font-semibold text-white">Limitations of this run</h2>{r.warnings.map((w, i) => <Notice key={i}>{w}</Notice>)}</Card>}
        </>
      )}
    </>
  );
}
