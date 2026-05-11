import type { AgentStep } from "../types";

const TOOL_ICONS: Record<string, string> = {
  read_resume: "📄",
  search_web: "🔍",
  save_application: "💾",
};

const TYPE_LABELS: Record<AgentStep["type"], string> = {
  tool_call: "Tool Call",
  tool_result: "Result",
  thought: "Reasoning",
};

interface Props {
  steps: AgentStep[];
}

export function AgentSteps({ steps }: Props) {
  if (steps.length === 0) return null;

  return (
    <div className="space-y-2">
      <h3 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">
        Agent Execution Trace
      </h3>
      <div className="space-y-1 max-h-72 overflow-y-auto rounded-lg border border-gray-200 bg-gray-50 p-3">
        {steps.map((step, i) => (
          <div key={i} className="flex items-start gap-2 text-xs">
            <span className="text-gray-400 w-5 shrink-0 mt-0.5">
              {step.iteration}
            </span>
            <span
              className={`shrink-0 px-1.5 py-0.5 rounded text-[10px] font-medium uppercase ${
                step.type === "tool_call"
                  ? "bg-blue-100 text-blue-700"
                  : step.type === "tool_result"
                    ? "bg-green-100 text-green-700"
                    : "bg-purple-100 text-purple-700"
              }`}
            >
              {TYPE_LABELS[step.type]}
            </span>

            {step.type === "tool_call" && step.tool && (
              <span className="text-gray-700">
                {TOOL_ICONS[step.tool] ?? "🔧"}{" "}
                <span className="font-mono font-medium">{step.tool}</span>
                {step.input && (
                  <span className="text-gray-500 ml-1">
                    ({Object.entries(step.input)
                      .map(([k, v]) => `${k}=${JSON.stringify(v).slice(0, 30)}`)
                      .join(", ")}
                    )
                  </span>
                )}
              </span>
            )}

            {step.type === "tool_result" && (
              <span className="text-gray-600 truncate">
                {step.result_preview}
              </span>
            )}

            {step.type === "thought" && (
              <span className="text-gray-600 italic truncate">{step.text}</span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
