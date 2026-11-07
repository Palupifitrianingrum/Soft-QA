import { useEffect, useState } from "react";
import { api } from "../api";
import type { PageProps } from "../App";
import type { Finding } from "../types";
import { AnalysisSelect, Notice, Title } from "../components/ui";
import { FindingCard } from "./Findings";

export default function SecurityCenter({ analysisId, setAnalysisId, status }: PageProps) {
  const [items, setItems] = useState<Finding[]>([]);
  const [err, setErr] = useState("");
  useEffect(() => { if (analysisId !== null) api.findings(analysisId).then((l) => setItems(l.filter((f) => f.category === "security"))).catch((e: Error) => setErr(e.message)); }, [analysisId]);
  return (
    <>
      <Title right={<AnalysisSelect value={analysisId} onChange={setAnalysisId} />}>Security Center</Title>
      {err && <Notice tone="red">{err}</Notice>}
      {status && !status.semgrep_available && <Notice>Semgrep is unavailable (not installed and no Docker fallback), so no security findings can be produced. See README.</Notice>}
      <p className="text-xs text-slate-400">Every item here comes from a Semgrep rule match with file, line and evidence; the LLM is not used to claim vulnerabilities.</p>
      {items.map((f) => <FindingCard key={f.id} f={f} />)}
      {!items.length && analysisId !== null && <p className="text-sm text-slate-500">No security findings for this analysis (this is not proof the code is secure).</p>}
    </>
  );
}
