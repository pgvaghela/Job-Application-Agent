import { useRef, useState } from "react";
import { api } from "../api/client";
import type { AnalyzeResponse } from "../types";

interface Props {
  onResult: (result: AnalyzeResponse) => void;
}

export function JobForm({ onResult }: Props) {
  const [jd, setJd] = useState("");
  const [userId, setUserId] = useState("default");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);

  const [resumeFile, setResumeFile] = useState<File | null>(null);
  const [uploadStatus, setUploadStatus] = useState<"idle" | "uploading" | "done" | "error">("idle");
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setResumeFile(file);
    setUploadStatus("uploading");
    try {
      await api.uploadResume(userId, file);
      setUploadStatus("done");
    } catch (err) {
      setUploadStatus("error");
      setError(err instanceof Error ? err.message : "Upload failed");
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!jd.trim()) return;

    setLoading(true);
    setError(null);
    setStatus("Agent is starting… reading your resume…");

    try {
      const statusMessages = [
        "Reading your resume…",
        "Researching the company…",
        "Analyzing skill gaps and keyword matches…",
        "Rewriting resume bullets to match the JD…",
        "Drafting your cover letter…",
        "Saving results to database…",
      ];
      let i = 0;
      const interval = setInterval(() => {
        i = Math.min(i + 1, statusMessages.length - 1);
        setStatus(statusMessages[i]);
      }, 8000);

      const result = await api.analyze(jd, userId);
      clearInterval(interval);
      setStatus(null);
      onResult(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
      setStatus(null);
    } finally {
      setLoading(false);
    }
  };

  const uploadLabel = {
    idle: "Upload Resume (.tex / .md)",
    uploading: "Uploading…",
    done: `✓ ${resumeFile?.name}`,
    error: "Upload failed — try again",
  }[uploadStatus];

  const uploadColor = {
    idle: "border-gray-300 text-gray-600 hover:border-indigo-400 hover:text-indigo-600",
    uploading: "border-indigo-300 text-indigo-500 cursor-wait",
    done: "border-green-400 text-green-700 bg-green-50",
    error: "border-red-400 text-red-600",
  }[uploadStatus];

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">
          User ID
        </label>
        <input
          type="text"
          value={userId}
          onChange={(e) => setUserId(e.target.value)}
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
          placeholder="default"
        />
      </div>

      {/* Resume upload */}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">
          Your Resume
        </label>
        <button
          type="button"
          onClick={() => fileInputRef.current?.click()}
          disabled={uploadStatus === "uploading"}
          className={`w-full border-2 border-dashed rounded-lg px-4 py-3 text-sm font-medium transition-colors text-left ${uploadColor}`}
        >
          {uploadLabel}
        </button>
        <input
          ref={fileInputRef}
          type="file"
          accept=".tex,.md,.txt"
          className="hidden"
          onChange={handleFileChange}
        />
        <p className="text-xs text-gray-400 mt-1">
          Accepts LaTeX (.tex), Markdown (.md), or plain text (.txt). Falls back to{" "}
          <code className="bg-gray-100 px-1 rounded">resumes/default.md</code> if no file uploaded.
        </p>
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">
          Job Description
        </label>
        <textarea
          value={jd}
          onChange={(e) => setJd(e.target.value)}
          rows={18}
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-indigo-500 resize-none"
          placeholder="Paste the full job description here…"
          disabled={loading}
        />
        <p className="text-xs text-gray-500 mt-1">
          {jd.trim().split(/\s+/).filter(Boolean).length} words
        </p>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {loading && status && (
        <div className="bg-indigo-50 border border-indigo-200 rounded-lg p-3 text-sm text-indigo-700 flex items-center gap-2">
          <span className="animate-spin inline-block w-4 h-4 border-2 border-indigo-400 border-t-transparent rounded-full" />
          {status}
        </div>
      )}

      <button
        type="submit"
        disabled={loading || !jd.trim()}
        className="w-full bg-indigo-600 text-white py-2.5 px-4 rounded-lg font-medium hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
      >
        {loading ? "Agent Running…" : "Run Agent →"}
      </button>
    </form>
  );
}
