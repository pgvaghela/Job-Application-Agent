import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { AgentStep, ApplicationDetail, AnalyzeResponse } from "../types";
import { AgentSteps } from "./AgentSteps";

async function downloadPdf(applicationId: string): Promise<string | null> {
  const res = await fetch(`/api/applications/${applicationId}/resume.pdf`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Compilation failed" }));
    return err.detail ?? "PDF generation failed";
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `resume_${applicationId}.pdf`;
  a.click();
  URL.revokeObjectURL(url);
  return null;
}

interface Props {
  result: AnalyzeResponse;
}

function ScoreBadge({ score }: { score: number | null }) {
  if (score === null) return null;
  const color =
    score >= 75
      ? "bg-green-100 text-green-800"
      : score >= 50
        ? "bg-yellow-100 text-yellow-800"
        : "bg-red-100 text-red-800";
  return (
    <span className={`inline-block px-2 py-0.5 rounded-full text-sm font-bold ${color}`}>
      {score}% match
    </span>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="border border-gray-200 rounded-lg overflow-hidden">
      <div className="bg-gray-50 px-4 py-2 border-b border-gray-200">
        <h3 className="font-semibold text-gray-800 text-sm">{title}</h3>
      </div>
      <div className="p-4">{children}</div>
    </div>
  );
}

export function ResultPanel({ result }: Props) {
  const [detail, setDetail] = useState<ApplicationDetail | null>(null);
  const [activeTab, setActiveTab] = useState<"overview" | "bullets" | "cover" | "trace">(
    "overview"
  );
  const [pdfError, setPdfError] = useState<string | null>(null);
  const [pdfLoading, setPdfLoading] = useState(false);

  useEffect(() => {
    api.getApplication(result.application_id).then(setDetail).catch(console.error);
  }, [result.application_id]);

  const handleDownloadPdf = async () => {
    setPdfLoading(true);
    setPdfError(null);
    const error = await downloadPdf(String(result.application_id));
    if (error) setPdfError(error);
    setPdfLoading(false);
  };

  const steps: AgentStep[] = result.agent_steps;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="bg-white rounded-xl border border-gray-200 p-5">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-lg font-bold text-gray-900">
              {detail?.job_title ?? "Analyzing…"}
            </h2>
            <p className="text-sm text-gray-500">{detail?.company_name}</p>
          </div>
          <div className="flex flex-col items-end gap-1">
            <div className="flex items-center gap-3">
              <ScoreBadge score={detail?.match_score ?? null} />
              {detail?.has_pdf && (
                <button
                  onClick={handleDownloadPdf}
                  disabled={pdfLoading}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-indigo-600 text-white text-xs font-medium rounded-lg hover:bg-indigo-700 disabled:opacity-60 disabled:cursor-wait transition-colors"
                >
                  {pdfLoading ? "Compiling…" : "↓ Download PDF"}
                </button>
              )}
            </div>
            {pdfError && (
              <p className="text-xs text-red-600 max-w-xs text-right">{pdfError}</p>
            )}
          </div>
        </div>
        {result.summary && (
          <div className="mt-4 text-sm text-gray-700 whitespace-pre-wrap leading-relaxed">
            {result.summary}
          </div>
        )}
      </div>

      {/* Tabs */}
      <div className="border-b border-gray-200">
        <nav className="-mb-px flex gap-6">
          {(["overview", "bullets", "cover", "trace"] as const).map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`pb-2 text-sm font-medium capitalize transition-colors ${
                activeTab === tab
                  ? "border-b-2 border-indigo-600 text-indigo-600"
                  : "text-gray-500 hover:text-gray-700"
              }`}
            >
              {tab === "bullets" ? "Resume Bullets" : tab === "cover" ? "Cover Letter" : tab === "trace" ? "Agent Trace" : "Overview"}
            </button>
          ))}
        </nav>
      </div>

      {/* Tab content */}
      {activeTab === "overview" && detail && (
        <div className="space-y-4">
          <Section title={`✅ Keyword Matches (${detail.keyword_matches.length})`}>
            <div className="flex flex-wrap gap-2">
              {detail.keyword_matches.map((kw) => (
                <span key={kw} className="bg-green-50 text-green-800 text-xs px-2 py-1 rounded-full border border-green-200">
                  {kw}
                </span>
              ))}
            </div>
          </Section>

          <Section title={`⚠️ Skill Gaps (${detail.skill_gaps.length})`}>
            <div className="flex flex-wrap gap-2">
              {detail.skill_gaps.map((gap) => (
                <span key={gap} className="bg-orange-50 text-orange-800 text-xs px-2 py-1 rounded-full border border-orange-200">
                  {gap}
                </span>
              ))}
            </div>
          </Section>

          {detail.company_info && (
            <Section title="🏢 Company Research">
              <p className="text-sm text-gray-700 whitespace-pre-wrap leading-relaxed">
                {detail.company_info}
              </p>
            </Section>
          )}
        </div>
      )}

      {activeTab === "bullets" && detail && (
        <div className="space-y-4">
          {detail.rewritten_bullets.map((b, i) => (
            <div key={i} className="border border-gray-200 rounded-lg overflow-hidden">
              <div className="bg-red-50 px-4 py-3">
                <p className="text-xs font-medium text-red-600 mb-1">ORIGINAL</p>
                <p className="text-sm text-gray-800">{b.original}</p>
              </div>
              <div className="bg-green-50 px-4 py-3">
                <p className="text-xs font-medium text-green-600 mb-1">REWRITTEN</p>
                <p className="text-sm text-gray-800">{b.rewritten}</p>
              </div>
              <div className="bg-gray-50 px-4 py-2 border-t border-gray-200">
                <p className="text-xs text-gray-500">
                  <span className="font-medium">Why:</span> {b.reason}
                </p>
              </div>
            </div>
          ))}
        </div>
      )}

      {activeTab === "cover" && detail?.cover_letter && (
        <Section title="📝 Cover Letter">
          <div className="text-sm text-gray-800 whitespace-pre-wrap leading-relaxed font-serif">
            {detail.cover_letter}
          </div>
          <button
            onClick={() => navigator.clipboard.writeText(detail.cover_letter ?? "")}
            className="mt-4 text-xs text-indigo-600 hover:underline"
          >
            Copy to clipboard
          </button>
        </Section>
      )}

      {activeTab === "trace" && (
        <AgentSteps steps={steps} />
      )}
    </div>
  );
}
