import { ArrowRight } from "lucide-react";
import { StageColumn } from "./StageColumn";

interface PipelineDeployment {
  id: string;
  agent_id: string;
  agent_name?: string;
  version_id: string;
  status: string;
  environment: string;
}

interface PipelineStage {
  stage: string;
  label: string;
  deployments: PipelineDeployment[];
  approval_gate: { enabled: boolean; required_approvers: number } | null;
}

const STAGE_STYLES: Record<string, { color: string; dot: string; text: string }> = {
  dev: { color: "border-gray-500/50 bg-gray-500/10", dot: "bg-gray-400", text: "text-gray-400" },
  staging: { color: "border-yellow-500/50 bg-yellow-500/10", dot: "bg-yellow-400", text: "text-yellow-400" },
  canary: { color: "border-blue-500/50 bg-blue-500/10", dot: "bg-blue-400", text: "text-blue-400" },
  production: { color: "border-green-500/50 bg-green-500/10", dot: "bg-green-400", text: "text-green-400" },
};

interface PipelineViewProps {
  stages: PipelineStage[];
  onPromote?: (deploymentId: string) => void;
  onDemote?: (deploymentId: string) => void;
}

export function PipelineView({ stages, onPromote, onDemote }: PipelineViewProps) {
  return (
    <div className="mb-6">
      <h2 className="mb-3 text-sm font-semibold text-white">Deployment Pipeline</h2>
      <div className="flex items-start gap-2 overflow-x-auto pb-2">
        {stages.map((stage, idx) => {
          const style = STAGE_STYLES[stage.stage] ?? STAGE_STYLES.dev;
          return (
            <div key={stage.stage} className="flex items-start">
              <StageColumn
                stage={stage.stage}
                label={stage.label}
                deployments={stage.deployments}
                color={style?.color ?? ''}
                dot={style?.dot ?? ''}
                text={style?.text ?? ''}
                isFirst={idx === 0}
                isLast={idx === stages.length - 1}
                onPromote={onPromote}
                onDemote={onDemote}
              />
              {idx < stages.length - 1 && (
                <div className="flex flex-col items-center self-center px-1 pt-4">
                  <ArrowRight size={16} className="text-gray-600" />
                  {stage.approval_gate?.enabled && (
                    <span className="mt-1 text-[9px] text-yellow-400">
                      {stage.approval_gate.required_approvers} approval{stage.approval_gate.required_approvers > 1 ? "s" : ""}
                    </span>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
