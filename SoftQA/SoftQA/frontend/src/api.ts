import type { Analysis, AnalysisOptions, Finding, FileContent, Project, ProjectDetail, Report, Stats, SystemStatus, TestCase, TestExecution } from "./types";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`/api${path}`, init);
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`;
    try {
      const j = await r.json();
      msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail ?? j);
    } catch { /* non-JSON error body */ }
    throw new Error(msg);
  }
  return (await r.json()) as T;
}
const post = <T,>(path: string, body?: unknown) =>
  req<T>(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) });

export const api = {
  status: () => req<SystemStatus>("/system/status"),
  stats: () => req<Stats>("/stats"),
  projects: () => req<Project[]>("/projects"),
  project: (id: number) => req<ProjectDetail>(`/projects/${id}`),
  file: (pid: number, fid: number) => req<FileContent>(`/projects/${pid}/files/${fid}`),
  upload: (file: File) => { const fd = new FormData(); fd.append("file", file); return req<ProjectDetail>("/projects/upload", { method: "POST", body: fd }); },
  startAnalysis: (pid: number, o: AnalysisOptions) => post<Analysis>(`/analysis/${pid}/start`, o),
  analyses: () => req<Analysis[]>("/analysis"),
  analysis: (id: number) => req<Analysis>(`/analysis/${id}`),
  findings: (id: number) => req<Finding[]>(`/analysis/${id}/findings`),
  tests: (id: number) => req<TestCase[]>(`/tests/${id}`),
  generateTests: (id: number) => post<TestCase[]>(`/tests/${id}/generate`),
  approve: (testId: number, approved: boolean) => post<TestCase>(`/tests/${testId}/approve`, { approved }),
  execute: (id: number) => post<TestExecution>(`/tests/${id}/execute`),
  executions: (id: number) => req<TestExecution[]>(`/tests/${id}/executions`),
  report: (id: number) => req<Report>(`/reports/${id}`),
  exportUrl: (id: number, fmt: "pdf" | "json") => `/api/reports/${id}/export?format=${fmt}`,
};
