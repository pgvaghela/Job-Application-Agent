export interface RewrittenBullet {
  original: string;
  rewritten: string;
  reason: string;
}

export interface AgentStep {
  iteration: number;
  type: "tool_call" | "tool_result" | "thought";
  tool?: string;
  input?: Record<string, unknown>;
  result_preview?: string;
  text?: string;
}

export interface AnalyzeResponse {
  application_id: string;
  summary: string;
  agent_steps: AgentStep[];
}

export interface ApplicationDetail {
  id: string;
  user_id: string;
  created_at: string;
  job_title: string;
  company_name: string;
  job_description: string;
  company_info: string | null;
  skill_gaps: string[];
  keyword_matches: string[];
  match_score: number | null;
  original_resume: string | null;
  rewritten_bullets: RewrittenBullet[];
  cover_letter: string | null;
  agent_steps: AgentStep[];
  has_pdf: boolean;
}

export interface ApplicationSummary {
  id: string;
  created_at: string;
  job_title: string;
  company_name: string;
  match_score: number | null;
}
