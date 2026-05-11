import { useEffect, useState } from "react";
import { api } from "./api/client";
import { JobForm } from "./components/JobForm";
import { ResultPanel } from "./components/ResultPanel";
import type { AnalyzeResponse, ApplicationSummary } from "./types";

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function ScorePill({ score }: { score: number | null }) {
  if (score === null) return <span className="text-xs text-gray-400">—</span>;
  const color =
    score >= 75
      ? "bg-green-100 text-green-800"
      : score >= 50
        ? "bg-yellow-100 text-yellow-800"
        : "bg-red-100 text-red-800";
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${color}`}>
      {score}%
    </span>
  );
}

export default function App() {
  const [result, setResult] = useState<AnalyzeResponse | null>(null);
  const [history, setHistory] = useState<ApplicationSummary[]>([]);
  const [userId, _setUserId] = useState("default");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const refreshHistory = () => {
    api.listApplications(userId).then(setHistory).catch(console.error);
  };

  useEffect(() => {
    refreshHistory();
  }, [userId]);

  const handleResult = (r: AnalyzeResponse) => {
    setResult(r);
    setSelectedId(r.application_id);
    refreshHistory();
  };

  const handleSelectHistory = (app: ApplicationSummary) => {
    // Build a synthetic AnalyzeResponse so ResultPanel can fetch the detail
    setResult({ application_id: app.id, summary: "", agent_steps: [] });
    setSelectedId(app.id);
  };

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col">
      {/* Top bar */}
      <header className="bg-white border-b border-gray-200 px-6 py-4 flex items-center gap-3">
        <div className="w-8 h-8 bg-indigo-600 rounded-lg flex items-center justify-center">
          <span className="text-white text-sm font-bold">J</span>
        </div>
        <div>
          <h1 className="text-base font-bold text-gray-900 leading-none">Job Application Agent</h1>
          <p className="text-xs text-gray-500 mt-0.5">Powered by Claude + Anthropic tool use</p>
        </div>
      </header>

      <div className="flex flex-1 overflow-hidden">
        {/* Sidebar — past applications */}
        <aside className="w-64 bg-white border-r border-gray-200 flex flex-col overflow-hidden">
          <div className="px-4 py-3 border-b border-gray-100">
            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
              Past Applications
            </p>
          </div>
          <div className="flex-1 overflow-y-auto">
            {history.length === 0 ? (
              <p className="text-xs text-gray-400 px-4 py-6 text-center">
                No applications yet. Run the agent to get started.
              </p>
            ) : (
              <ul className="divide-y divide-gray-100">
                {history.map((app) => (
                  <li key={app.id}>
                    <button
                      onClick={() => handleSelectHistory(app)}
                      className={`w-full text-left px-4 py-3 hover:bg-gray-50 transition-colors ${
                        selectedId === app.id ? "bg-indigo-50" : ""
                      }`}
                    >
                      <p className="text-sm font-medium text-gray-800 truncate">
                        {app.job_title || "Unknown role"}
                      </p>
                      <p className="text-xs text-gray-500 truncate">{app.company_name}</p>
                      <div className="flex items-center justify-between mt-1">
                        <span className="text-[10px] text-gray-400">{formatDate(app.created_at)}</span>
                        <ScorePill score={app.match_score} />
                      </div>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </aside>

        {/* Main content */}
        <main className="flex-1 overflow-y-auto">
          <div className="max-w-5xl mx-auto px-6 py-8">
            {result ? (
              <div className="space-y-6">
                <button
                  onClick={() => { setResult(null); setSelectedId(null); }}
                  className="text-sm text-indigo-600 hover:underline flex items-center gap-1"
                >
                  ← New Analysis
                </button>
                <ResultPanel result={result} />
              </div>
            ) : (
              <div className="max-w-2xl mx-auto">
                <div className="mb-8">
                  <h2 className="text-2xl font-bold text-gray-900">Analyze a Job Description</h2>
                  <p className="text-gray-500 mt-1 text-sm">
                    Paste the full JD below. The agent will read your resume, research the company,
                    identify skill gaps, rewrite resume bullets, and draft a cover letter — all autonomously.
                  </p>
                </div>
                <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm">
                  <JobForm onResult={handleResult} />
                </div>
              </div>
            )}
          </div>
        </main>
      </div>
    </div>
  );
}
