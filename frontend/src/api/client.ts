import type {
  AnalyzeResponse,
  ApplicationDetail,
  ApplicationSummary,
} from "../types";

const BASE = "/api";

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Request failed");
  }
  return res.json();
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Request failed");
  }
  return res.json();
}

export const api = {
  analyze: (jobDescription: string, userId = "default") =>
    post<AnalyzeResponse>("/analyze", {
      job_description: jobDescription,
      user_id: userId,
    }),

  listApplications: (userId = "default") =>
    get<ApplicationSummary[]>(`/applications?user_id=${userId}`),

  getApplication: (id: string) =>
    get<ApplicationDetail>(`/applications/${id}`),

  getResume: (userId = "default") =>
    get<{ content: string }>(`/resume/${userId}`),

  updateResume: (userId: string, content: string) =>
    post<{ content: string }>(`/resume/${userId}`, { content }),

  uploadResume: async (userId: string, file: File): Promise<{ content: string }> => {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(`${BASE}/resume/${userId}/upload`, {
      method: "POST",
      body: form,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail ?? "Upload failed");
    }
    return res.json();
  },
};
