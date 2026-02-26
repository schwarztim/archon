import type { PostureScoreResult } from "@/api/sentinelscan";

interface PostureGaugeProps {
  posture: PostureScoreResult | null;
  serviceCount: number;
}

function scoreColor(score: number): string {
  if (score >= 80) return "text-green-400";
  if (score >= 60) return "text-yellow-400";
  return "text-red-400";
}

function strokeColor(score: number): string {
  if (score >= 80) return "stroke-green-400";
  if (score >= 60) return "stroke-yellow-400";
  return "stroke-red-400";
}

export function PostureGauge({ posture, serviceCount }: PostureGaugeProps) {
  return (
    <div className="flex flex-col items-center justify-center rounded-lg border border-surface-border bg-surface-raised p-6">
      <p className="mb-1 text-xs text-gray-500 uppercase tracking-wider">Security Posture</p>
      {posture ? (
        <>
          <div className="relative my-2">
            <svg className="h-28 w-28" viewBox="0 0 120 120">
              <circle cx="60" cy="60" r="50" fill="none" stroke="currentColor" strokeWidth="8" className="text-white/10" />
              <circle
                cx="60" cy="60" r="50" fill="none" strokeWidth="8"
                className={strokeColor(posture.score)}
                strokeDasharray={`${posture.score * 3.14} ${(100 - posture.score) * 3.14}`}
                strokeLinecap="round"
                transform="rotate(-90 60 60)"
              />
            </svg>
            <span className={`absolute inset-0 flex items-center justify-center text-3xl font-bold ${scoreColor(posture.score)}`}>
              {posture.score}
            </span>
          </div>
          <p className={`text-sm font-medium ${scoreColor(posture.score)}`}>{posture.grade}</p>
          <p className="text-xs text-gray-500">{serviceCount} services monitored</p>
          <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
            <span className="text-gray-500">Unauthorized:</span>
            <span className="text-white">{posture.breakdown.unauthorized}</span>
            <span className="text-gray-500">Critical:</span>
            <span className="text-white">{posture.breakdown.critical}</span>
            <span className="text-gray-500">Data Exposure:</span>
            <span className="text-white">{posture.breakdown.data_exposure}</span>
            <span className="text-gray-500">Policy Violations:</span>
            <span className="text-white">{posture.breakdown.policy_violations}</span>
          </div>
        </>
      ) : (
        <>
          <div className="relative my-2">
            <svg className="h-28 w-28" viewBox="0 0 120 120">
              <circle cx="60" cy="60" r="50" fill="none" stroke="currentColor" strokeWidth="8" className="text-white/10" />
            </svg>
            <span className="absolute inset-0 flex items-center justify-center text-3xl font-bold text-gray-500">—</span>
          </div>
          <p className="text-xs text-gray-500 text-center">Run a scan to see your posture score</p>
        </>
      )}
    </div>
  );
}
