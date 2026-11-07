import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type { PageProps } from "../App";
import type { FileContent, FileInfo, Finding } from "../types";
import { AnalysisSelect, Card, Notice, SEV_HEX, Title } from "../components/ui";
import { FindingCard } from "./Findings";

const KW = "def|class|return|if|elif|else|for|while|import|from|try|except|finally|raise|with|as|in|not|and|or|is|None|True|False|lambda|yield|pass|break|continue|async|await";
const TOKEN = new RegExp(`(#.*$)|("(?:[^"\\\\]|\\\\.)*"|'(?:[^'\\\\]|\\\\.)*')|\\b(${KW})\\b|\\b(\\d+\\.?\\d*)\\b`, "g");

/** Tiny dependency-free Python highlighter (comments, strings, keywords, numbers). */
function highlight(line: string) {
  const out: (string | JSX.Element)[] = []; let last = 0; let m: RegExpExecArray | null; TOKEN.lastIndex = 0;
  while ((m = TOKEN.exec(line))) {
    if (m.index > last) out.push(line.slice(last, m.index));
    const cls = m[1] ? "text-slate-500" : m[2] ? "text-emerald-300" : m[3] ? "text-purple-300" : "text-amber-300";
    out.push(<span key={m.index} className={cls}>{m[0]}</span>); last = m.index + m[0].length;
    if (m[0] === "") TOKEN.lastIndex++;
  }
  out.push(line.slice(last)); return out;
}

export default function CodeExplorer({ analysisId, setAnalysisId }: PageProps) {
  const [files, setFiles] = useState<FileInfo[]>([]);
  const [pid, setPid] = useState<number | null>(null);
  const [findings, setFindings] = useState<Finding[]>([]);
  const [file, setFile] = useState<FileContent | null>(null);
  const [line, setLine] = useState<number | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    if (analysisId === null) return;
    setFile(null); setLine(null);
    Promise.all([api.analysis(analysisId), api.findings(analysisId)]).then(async ([a, f]) => { setPid(a.project_id); setFindings(f); setFiles((await api.project(a.project_id)).files); }).catch((e: Error) => setErr(e.message));
  }, [analysisId]);
  const open = (f: FileInfo) => { if (pid !== null) { setLine(null); api.file(pid, f.id).then(setFile).catch((e: Error) => setErr(e.message)); } };
  const mine = useMemo(() => findings.filter((f) => f.file === file?.path), [findings, file]);
  const lineSev = (n: number) => mine.filter((f) => n >= f.line_start && n <= f.line_end).sort((a, b) => "critical high medium low info".indexOf(a.severity) - "critical high medium low info".indexOf(b.severity))[0];
  const selected = line === null ? [] : mine.filter((f) => line >= f.line_start && line <= f.line_end);
  return (
    <>
      <Title right={<AnalysisSelect value={analysisId} onChange={setAnalysisId} />}>Code Explorer</Title>
      {err && <Notice tone="red">{err}</Notice>}
      <div className="grid gap-3 lg:grid-cols-[16rem_1fr]">
        <Card className="max-h-[70vh] overflow-auto">
          {files.map((f) => {
            const n = findings.filter((x) => x.file === f.path).length;
            return <button key={f.id} onClick={() => open(f)} className={`flex w-full items-center justify-between rounded px-2 py-1 text-left text-xs hover:bg-slate-800 ${file?.id === f.id ? "bg-slate-800 text-white" : "text-slate-300"}`}><span className="truncate">{f.path}</span>{n > 0 && <span className="ml-2 rounded bg-red-500/20 px-1.5 text-red-300">{n}</span>}</button>;
          })}
        </Card>
        <div className="min-w-0 space-y-3">
          {!file ? <p className="text-sm text-slate-500">Select a file. Click a highlighted line to see its findings.</p> : (
            <Card className="overflow-x-auto p-0">
              <pre className="py-2 text-xs leading-5">
                {file.content.split("\n").map((l, i) => {
                  const n = i + 1; const s = lineSev(n);
                  return (
                    <div key={n} onClick={() => s && setLine(n)} className={`flex ${s ? "cursor-pointer hover:bg-slate-800/60" : ""} ${line === n ? "bg-slate-800" : ""}`} style={{ borderLeft: `3px solid ${s ? SEV_HEX[s.severity] : "transparent"}` }}>
                      <span className="w-12 shrink-0 select-none pr-3 text-right text-slate-600">{n}</span><code className="whitespace-pre">{highlight(l)}</code>
                    </div>
                  );
                })}
              </pre>
            </Card>
          )}
          {selected.map((f) => <FindingCard key={f.id} f={f} />)}
        </div>
      </div>
    </>
  );
}
