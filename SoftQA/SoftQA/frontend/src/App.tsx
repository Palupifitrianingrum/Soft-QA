import { useCallback, useEffect, useState } from "react";
import { Bug, FileCode2, FileText, FlaskConical, LayoutDashboard, PlayCircle, ShieldAlert, Sparkles } from "lucide-react";
import { api } from "./api";
import type { SystemStatus } from "./types";
import { Notice } from "./components/ui";
import Overview from "./pages/Overview";
import NewAnalysis from "./pages/NewAnalysis";
import CodeExplorer from "./pages/CodeExplorer";
import Findings from "./pages/Findings";
import TestCenter from "./pages/TestCenter";
import SecurityCenter from "./pages/SecurityCenter";
import Reports from "./pages/Reports";

const NAV = [
  { id: "overview", label: "Overview", icon: LayoutDashboard },
  { id: "new", label: "New Analysis", icon: PlayCircle },
  { id: "explorer", label: "Code Explorer", icon: FileCode2 },
  { id: "findings", label: "Findings", icon: Bug },
  { id: "tests", label: "Test Center", icon: FlaskConical },
  { id: "security", label: "Security Center", icon: ShieldAlert },
  { id: "reports", label: "Reports", icon: FileText },
] as const;
type Page = (typeof NAV)[number]["id"];

export interface PageProps { analysisId: number | null; setAnalysisId: (id: number) => void; go: (p: Page) => void; status: SystemStatus | null }

export default function App() {
  const [page, setPage] = useState<Page>("overview");
  const [analysisId, setAnalysisIdRaw] = useState<number | null>(null);
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [backendDown, setBackendDown] = useState(false);
  const setAnalysisId = useCallback((id: number) => setAnalysisIdRaw(id), []);
  useEffect(() => { api.status().then((s) => { setStatus(s); setBackendDown(false); }).catch(() => setBackendDown(true)); }, [page]);
  const props: PageProps = { analysisId, setAnalysisId, go: setPage, status };
  return (
    <div className="flex min-h-screen flex-col md:flex-row">
      <aside className="border-b border-slate-800 bg-slate-950/70 p-3 md:w-56 md:border-b-0 md:border-r">
        <div className="mb-4 flex items-center gap-2 px-2 text-lg font-bold text-white"><Sparkles className="text-cyan-400" size={20} />SOFT <span className="text-purple-400">QA</span></div>
        <nav className="flex gap-1 overflow-x-auto md:flex-col">
          {NAV.map(({ id, label, icon: Icon }) => (
            <button key={id} onClick={() => setPage(id)} className={`flex items-center gap-2 whitespace-nowrap rounded-lg px-3 py-2 text-sm ${page === id ? "bg-purple-500/20 text-white" : "text-slate-400 hover:bg-slate-800/60"}`}>
              <Icon size={16} />{label}
            </button>
          ))}
        </nav>
      </aside>
      <main className="flex-1 space-y-3 p-4 md:p-6">
        {backendDown && <Notice tone="red">Cannot reach the backend. Start it with <code>uvicorn app.main:app --reload</code> in <code>backend/</code> (port 8000).</Notice>}
        {status && !status.ai_configured && <Notice>Gemini AI is not available: {status.ai_message} AI review and AI test generation are disabled; static analysis and security scanning still work.</Notice>}
        {page === "overview" && <Overview {...props} />}
        {page === "new" && <NewAnalysis {...props} />}
        {page === "explorer" && <CodeExplorer {...props} />}
        {page === "findings" && <Findings {...props} />}
        {page === "tests" && <TestCenter {...props} />}
        {page === "security" && <SecurityCenter {...props} />}
        {page === "reports" && <Reports {...props} />}
      </main>
    </div>
  );
}
