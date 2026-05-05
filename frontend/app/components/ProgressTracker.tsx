"use client";

export type SectionStatus = "pending" | "in_progress" | "done";

export interface ProgressState {
  problem: SectionStatus;
  product: SectionStatus;
  features: SectionStatus;
  team_traction: SectionStatus;
  investment: SectionStatus;
  exit_strategy: SectionStatus;
}

const sections = [
  { key: "problem", label: "Problem", number: "01" },
  { key: "product", label: "Product", number: "02" },
  { key: "features", label: "Features", number: "03" },
  { key: "team_traction", label: "Team & Traction", number: "04" },
  { key: "investment", label: "Investment Plan", number: "05" },
  { key: "exit_strategy", label: "Exit Strategy", number: "06" },
] as const;

export default function ProgressTracker({ status }: { status: ProgressState }) {
  const doneCount = Object.values(status).filter((s) => s === "done").length;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wider">Plan Progress</h2>
        <span className="text-xs font-medium px-2 py-1 rounded-full bg-blue-500/10 text-blue-400 border border-blue-500/20">
          {doneCount}/{sections.length}
        </span>
      </div>

      <div className="space-y-2.5">
        {sections.map((section) => {
          const s = status[section.key as keyof ProgressState];
          const isActive = s === "in_progress";
          const isDone = s === "done";

          return (
            <div
              key={section.key}
              className={`rounded-xl p-3 relative overflow-hidden border transition-all duration-300 ${
                isActive
                  ? "bg-blue-600/10 border-blue-500/30"
                  : isDone
                  ? "bg-slate-800/40 border-slate-700/50"
                  : "bg-slate-900/50 border-slate-800/50 opacity-60"
              }`}
            >
              {isActive && (
                <div className="absolute left-0 top-0 bottom-0 w-[3px] bg-blue-500 rounded-l-xl" />
              )}

              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <span className={`text-xs font-bold font-mono ${isActive ? "text-blue-400" : "text-slate-500"}`}>
                    {section.number}
                  </span>
                  <div
                    className={`w-2.5 h-2.5 rounded-full transition-colors duration-300 ${
                      isDone ? "bg-emerald-500" : isActive ? "bg-blue-500" : "bg-slate-600"
                    }`}
                  />
                  <span className={`text-sm font-medium ${isActive ? "text-slate-100" : isDone ? "text-slate-300" : "text-slate-500"}`}>
                    {section.label}
                  </span>
                </div>

                {isDone && (
                  <span className="flex items-center justify-center w-5 h-5 rounded-full bg-emerald-500/20 text-emerald-400">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                      <polyline points="20 6 9 17 4 12" />
                    </svg>
                  </span>
                )}
              </div>

              {isActive && (
                <p className="text-xs text-blue-300/80 ml-[42px] mt-2">
                  Gathering details for this section...
                </p>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
