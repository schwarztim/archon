import { Trophy, Bot } from "lucide-react";

export interface LeaderboardAgent {
  id: string;
  name: string;
  execution_count: number;
}

interface AgentLeaderboardProps {
  agents: LeaderboardAgent[];
}

export function AgentLeaderboard({ agents }: AgentLeaderboardProps) {
  const maxCount = Math.max(...agents.map((a) => a.execution_count), 1);

  if (agents.length === 0) {
    return (
      <div className="rounded-lg border border-[#2a2d37] bg-[#1a1d27]">
        <div className="flex items-center gap-2 border-b border-[#2a2d37] px-4 py-3">
          <Trophy size={14} className="text-yellow-400" />
          <h2 className="text-sm font-semibold text-white">Agent Leaderboard</h2>
        </div>
        <div className="flex flex-col items-center justify-center py-8">
          <Bot size={32} className="mb-2 text-gray-600" />
          <p className="text-sm text-gray-500">No agent data yet</p>
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-[#2a2d37] bg-[#1a1d27]">
      <div className="flex items-center gap-2 border-b border-[#2a2d37] px-4 py-3">
        <Trophy size={14} className="text-yellow-400" />
        <h2 className="text-sm font-semibold text-white">Agent Leaderboard</h2>
      </div>
      <div className="p-4 space-y-3">
        {agents.slice(0, 5).map((agent, idx) => (
          <div key={agent.id} className="flex items-center gap-3">
            <span className="w-5 text-right text-xs font-bold text-gray-500">
              #{idx + 1}
            </span>
            <div className="min-w-0 flex-1">
              <div className="mb-1 flex items-center justify-between">
                <span className="truncate text-sm font-medium text-white">
                  {agent.name}
                </span>
                <span className="ml-2 shrink-0 text-xs text-gray-400">
                  {agent.execution_count} runs
                </span>
              </div>
              <div className="h-1.5 w-full rounded-full bg-[#2a2d37]">
                <div
                  className="h-1.5 rounded-full bg-purple-500 transition-all"
                  style={{ width: `${(agent.execution_count / maxCount) * 100}%` }}
                />
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
