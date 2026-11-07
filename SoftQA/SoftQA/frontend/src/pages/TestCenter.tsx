import { useEffect, useState } from "react";
import { api } from "../api";
import type { PageProps } from "../App";
import type { TestCase, TestExecution } from "../types";
import { AnalysisSelect, Btn, Card, Notice, Tag, Title } from "../components/ui";

export default function TestCenter({ analysisId, setAnalysisId, status }: PageProps) {
  const [tests, setTests] = useState<TestCase[]>([]);
  const [execs, setExecs] = useState<TestExecution[]>([]);
  const [err, setErr] = useState(""); const [busy, setBusy] = useState(""); const [openId, setOpenId] = useState<number | null>(null);
  const load = (id: number) => Promise.all([api.tests(id), api.executions(id)]).then(([t, e]) => { setTests(t); setExecs(e); }).catch((e: Error) => setErr(e.message));
  useEffect(() => { if (analysisId !== null) { setErr(""); load(analysisId); } }, [analysisId]);
  const run = async (label: string, fn: () => Promise<unknown>) => { if (analysisId === null) return; setErr(""); setBusy(label); try { await fn(); await load(analysisId); } catch (e) { setErr((e as Error).message); } finally { setBusy(""); } };
  const last = execs[execs.length - 1];
  const approved = tests.filter((t) => t.approved).length;
  return (
    <>
      <Title right={<AnalysisSelect value={analysisId} onChange={setAnalysisId} />}>Test Center</Title>
      {err && <Notice tone="red">{err}</Notice>}
      {status && !status.docker_available && <Notice>Test execution is disabled: {status.docker_message} Generated tests can still be reviewed and approved.</Notice>}
      <div className="flex flex-wrap items-center gap-2">
        <Btn disabled={!!busy || analysisId === null || !status?.ai_configured} title={!status?.ai_configured ? "Requires GEMINI_API_KEY" : ""} onClick={() => run("gen", () => api.generateTests(analysisId!))}>{busy === "gen" ? "Generating…" : "Generate tests (AI)"}</Btn>
        <Btn disabled={!!busy || !approved || !status?.docker_available} onClick={() => run("exec", () => api.execute(analysisId!))}>{busy === "exec" ? "Running in sandbox…" : `Run ${approved} approved test(s)`}</Btn>
        <span className="text-xs text-slate-400">Review the code, approve what you trust, then run. Nothing runs on the host.</span>
      </div>
      {last && (
        <Card className="space-y-2 text-sm">
          <div className="flex flex-wrap gap-2"><Tag tone="green">{last.passed} passed</Tag><Tag tone={last.failed ? "red" : "slate"}>{last.failed} failed</Tag><Tag tone={last.errors ? "red" : "slate"}>{last.errors} errors</Tag><Tag>{last.duration_seconds.toFixed(1)}s</Tag><Tag tone="cyan">coverage {last.coverage_percent === null ? "n/a" : `${last.coverage_percent.toFixed(1)}%`}</Tag><Tag>{last.status}</Tag></div>
          {last.message && <Notice>{last.message}</Notice>}
          <details><summary className="cursor-pointer text-xs text-slate-400">stdout / stderr</summary><pre className="mt-2 max-h-64 overflow-auto rounded bg-slate-950 p-2 text-xs">{last.stdout}{last.stderr && `\n--- stderr ---\n${last.stderr}`}</pre></details>
        </Card>
      )}
      {tests.map((t) => (
        <Card key={t.id} className="space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-xs text-slate-400">{t.test_id}</span><span className="text-sm font-medium text-white">{t.test_name}</span><Tag tone="purple">{t.test_type}</Tag><Tag>{t.priority}</Tag>
            {t.validation_status === "rejected" ? <Tag tone="red">rejected by validation</Tag> : t.last_result ? <Tag tone={t.last_result === "passed" ? "green" : "red"}>{t.last_result}</Tag> : <Tag>not run</Tag>}
            <div className="ml-auto flex gap-2"><Btn kind="ghost" onClick={() => setOpenId(openId === t.id ? null : t.id)}>{openId === t.id ? "Hide code" : "Review code"}</Btn>
              <Btn kind={t.approved ? "ghost" : "primary"} disabled={t.validation_status !== "valid" || !!busy} onClick={() => run("ap", () => api.approve(t.id, !t.approved))}>{t.approved ? "Revoke" : "Approve"}</Btn></div>
          </div>
          <p className="text-xs text-slate-300">{t.description}</p>
          <p className="text-xs text-slate-400">Expected: {t.expected_result}</p>
          {t.validation_notes.length > 0 && <Notice tone="red">{t.validation_notes.join("; ")}</Notice>}
          {openId === t.id && <pre className="overflow-x-auto rounded bg-slate-950 p-3 text-xs text-cyan-100">{t.code}</pre>}
        </Card>
      ))}
      {!tests.length && analysisId !== null && <p className="text-sm text-slate-500">No test cases yet.</p>}
    </>
  );
}
