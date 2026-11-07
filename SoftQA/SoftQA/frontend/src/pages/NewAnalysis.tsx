import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { PageProps } from "../App";
import type { Analysis, AnalysisOptions, Project } from "../types";
import { Btn, Card, Notice, Title } from "../components/ui";

export default function NewAnalysis({ setAnalysisId, go, status }: PageProps) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [pid, setPid] = useState<number | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [opts, setOpts] = useState<AnalysisOptions>({ use_ai: true, run_ruff: true, run_semgrep: true, max_ai_files: 15 });
  const [run, setRun] = useState<Analysis | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => { api.projects().then((p) => { setProjects(p); if (p.length) setPid(p[0].id); }).catch((e: Error) => setErr(e.message)); return () => window.clearInterval(timer.current); }, []);

  const upload = async () => {
    if (!file) return;
    setErr(""); setBusy(true);
    try { const p = await api.upload(file); setProjects((l) => [p, ...l]); setPid(p.id); setFile(null); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  const start = async () => {
    if (pid === null) return;
    setErr(""); setBusy(true);
    try {
      const a = await api.startAnalysis(pid, opts); setRun(a); setAnalysisId(a.id);
      timer.current = window.setInterval(async () => {
        try { const cur = await api.analysis(a.id); setRun(cur); if (cur.status === "completed" || cur.status === "failed") { window.clearInterval(timer.current); setBusy(false); } }
        catch (e) { window.clearInterval(timer.current); setBusy(false); setErr((e as Error).message); }
      }, 1500);
    } catch (e) { setErr((e as Error).message); setBusy(false); }
  };
  const flag = (k: "use_ai" | "run_ruff" | "run_semgrep", label: string, off?: boolean) => (
    <label className={`flex items-center gap-2 text-sm ${off ? "opacity-50" : ""}`}><input type="checkbox" checked={opts[k]} onChange={(e) => setOpts({ ...opts, [k]: e.target.checked })} />{label}</label>
  );
  return (
    <>
      <Title>New Analysis</Title>
      {err && <Notice tone="red">{err}</Notice>}
      <div className="grid gap-3 lg:grid-cols-2">
        <Card className="space-y-3">
          <h2 className="text-sm font-semibold">1. Upload source code</h2>
          <input type="file" accept=".py,.zip" onChange={(e) => setFile(e.target.files?.[0] ?? null)} className="block w-full text-sm text-slate-300 file:mr-3 file:rounded-lg file:border-0 file:bg-slate-800 file:px-3 file:py-1.5 file:text-slate-200" />
          <p className="text-xs text-slate-500">A .py file or a .zip project (max {status?.max_upload_mb ?? 10} MB). Uploaded code is never executed on the backend host.</p>
          <Btn onClick={upload} disabled={!file || busy}>Upload</Btn>
          <select value={pid ?? ""} onChange={(e) => setPid(Number(e.target.value))} className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-1.5 text-sm">
            {!projects.length && <option value="">No projects yet</option>}
            {projects.map((p) => <option key={p.id} value={p.id}>#{p.id} {p.name} ({p.file_count} files)</option>)}
          </select>
        </Card>
        <Card className="space-y-3">
          <h2 className="text-sm font-semibold">2. Options</h2>
          {flag("run_ruff", "Ruff lint")}{flag("run_semgrep", "Semgrep security scan")}{flag("use_ai", "AI code review (Gemini)", !status?.ai_configured)}
          {!status?.ai_configured && <p className="text-xs text-amber-300">AI is not configured; the run will complete without AI findings and say so.</p>}
          <Btn onClick={start} disabled={pid === null || busy}>Start analysis</Btn>
        </Card>
      </div>
      {run && (
        <Card className="space-y-2">
          <div className="flex items-center justify-between text-sm"><span>Analysis #{run.id}: <b>{run.status}</b></span><span className="text-slate-400">stage: {run.stage}</span></div>
          <div className="h-1.5 overflow-hidden rounded bg-slate-800"><div className={`h-full ${run.status === "failed" ? "bg-red-500" : "bg-gradient-to-r from-purple-500 to-cyan-400"} ${run.status === "running" || run.status === "pending" ? "w-2/3 animate-pulse" : "w-full"}`} /></div>
          {run.error && <Notice tone="red">{run.error}</Notice>}
          {run.warnings.map((w, i) => <Notice key={i}>{w}</Notice>)}
          {run.status === "completed" && <div className="flex items-center gap-3"><span className="text-sm">{run.findings_count} findings</span><Btn onClick={() => go("findings")}>View findings</Btn></div>}
        </Card>
      )}
    </>
  );
}
