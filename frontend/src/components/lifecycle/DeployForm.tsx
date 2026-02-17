import { useState } from "react";
import { Rocket, Loader2, ChevronDown, CheckCircle } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { StrategySelector } from "./StrategySelector";

interface AgentDef {
  id: string;
  name: string;
  version: number;
}

interface DeployFormProps {
  agents: AgentDef[];
  onDeploy: (payload: {
    agent_id: string;
    version_id: string;
    environment: string;
    strategy_type: string;
    replicas: number;
    canary_percentage: number;
    blue_green_preview: boolean;
    rollback_threshold: number;
    pre_deploy_checks: boolean;
  }) => Promise<void>;
  onCancel: () => void;
}

export function DeployForm({ agents, onDeploy, onCancel }: DeployFormProps) {
  const [agentId, setAgentId] = useState("");
  const [versionId, setVersionId] = useState("1");
  const [environment, setEnvironment] = useState("staging");
  const [strategy, setStrategy] = useState("rolling");
  const [replicas, setReplicas] = useState("2");
  const [canaryPct, setCanaryPct] = useState("10");
  const [blueGreenPreview, setBlueGreenPreview] = useState(false);
  const [rollbackThreshold, setRollbackThreshold] = useState("0.05");
  const [preDeployChecks, setPreDeployChecks] = useState(true);
  const [creating, setCreating] = useState(false);
  const [agentSearch, setAgentSearch] = useState("");

  const selectedAgent = agents.find((a) => a.id === agentId);
  const versionOptions = selectedAgent
    ? Array.from({ length: selectedAgent.version }, (_, i) => i + 1)
    : [1, 2, 3];

  const filteredAgents = agents.filter((a) =>
    a.name.toLowerCase().includes(agentSearch.toLowerCase()),
  );

  async function handleSubmit() {
    if (!agentId || !versionId) return;
    setCreating(true);
    try {
      await onDeploy({
        agent_id: agentId,
        version_id: versionId,
        environment,
        strategy_type: strategy,
        replicas: parseInt(replicas) || 2,
        canary_percentage: parseInt(canaryPct) || 10,
        blue_green_preview: blueGreenPreview,
        rollback_threshold: parseFloat(rollbackThreshold) || 0.05,
        pre_deploy_checks: preDeployChecks,
      });
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="mb-6 rounded-lg border border-[#2a2d37] bg-[#1a1d27] p-4">
      <h3 className="mb-4 text-sm font-semibold text-white">New Deployment</h3>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {/* Agent selector with search */}
        <div>
          <label className="mb-1 block text-xs text-gray-400">Agent *</label>
          <div className="relative">
            <input
              type="text"
              placeholder="Search agents…"
              value={agentId ? (selectedAgent?.name ?? agentId.slice(0, 8)) : agentSearch}
              onChange={(e) => {
                setAgentSearch(e.target.value);
                setAgentId("");
              }}
              className="h-9 w-full rounded-md border border-[#2a2d37] bg-[#0f1117] px-3 text-sm text-white placeholder-gray-600"
            />
            {!agentId && agentSearch && filteredAgents.length > 0 && (
              <div className="absolute z-10 mt-1 max-h-40 w-full overflow-y-auto rounded-md border border-[#2a2d37] bg-[#0f1117]">
                {filteredAgents.map((a) => (
                  <button
                    key={a.id}
                    type="button"
                    onClick={() => {
                      setAgentId(a.id);
                      setAgentSearch("");
                      setVersionId("1");
                    }}
                    className="w-full px-3 py-1.5 text-left text-xs text-white hover:bg-white/5"
                  >
                    {a.name}{" "}
                    <span className="text-gray-500">({a.id.slice(0, 8)}…)</span>
                  </button>
                ))}
              </div>
            )}
            {agentId && (
              <button
                type="button"
                onClick={() => {
                  setAgentId("");
                  setAgentSearch("");
                }}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-300"
              >
                ×
              </button>
            )}
          </div>
        </div>

        {/* Version dropdown with version number */}
        <div>
          <label className="mb-1 block text-xs text-gray-400">Version *</label>
          <div className="relative">
            <select
              value={versionId}
              onChange={(e) => setVersionId(e.target.value)}
              className="h-9 w-full appearance-none rounded-md border border-[#2a2d37] bg-[#0f1117] px-3 pr-8 text-sm text-white"
            >
              {versionOptions.map((v) => (
                <option key={v} value={String(v)}>
                  v{v}
                </option>
              ))}
            </select>
            <ChevronDown
              size={14}
              className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-500"
            />
          </div>
        </div>

        {/* Environment selector */}
        <div>
          <label className="mb-1 block text-xs text-gray-400">Environment *</label>
          <div className="grid grid-cols-3 gap-1">
            {[
              { value: "dev", label: "Dev" },
              { value: "staging", label: "Staging" },
              { value: "production", label: "Production" },
            ].map((env) => (
              <button
                key={env.value}
                type="button"
                onClick={() => setEnvironment(env.value)}
                className={`rounded-md border px-2 py-1.5 text-xs transition-colors ${
                  environment === env.value
                    ? "border-purple-500/50 bg-purple-500/10 text-purple-400"
                    : "border-[#2a2d37] bg-[#0f1117] text-gray-400 hover:border-gray-500"
                }`}
              >
                {env.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Strategy selector */}
      <div className="mt-4">
        <StrategySelector
          strategy={strategy}
          onStrategyChange={setStrategy}
          replicas={replicas}
          onReplicasChange={setReplicas}
          canaryPct={canaryPct}
          onCanaryPctChange={setCanaryPct}
          blueGreenPreview={blueGreenPreview}
          onBlueGreenPreviewChange={setBlueGreenPreview}
        />
      </div>

      {/* Advanced settings */}
      <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div>
          <label className="mb-1 block text-xs text-gray-400">Auto-Rollback Threshold</label>
          <input
            type="number"
            min={0}
            max={1}
            step={0.01}
            value={rollbackThreshold}
            onChange={(e) => setRollbackThreshold(e.target.value)}
            className="h-9 w-full rounded-md border border-[#2a2d37] bg-[#0f1117] px-3 text-sm text-white"
          />
          <p className="mt-0.5 text-[10px] text-gray-600">Error rate to trigger rollback (0-1)</p>
        </div>

        <div className="flex items-center gap-2 pt-5">
          <input
            type="checkbox"
            checked={preDeployChecks}
            onChange={(e) => setPreDeployChecks(e.target.checked)}
            className="h-4 w-4 rounded border-gray-600 accent-purple-500"
          />
          <label className="text-xs text-gray-400">
            <CheckCircle size={12} className="mr-1 inline text-green-400" />
            Run pre-deploy checks
          </label>
        </div>
      </div>

      {/* Actions */}
      <div className="mt-4 flex gap-2">
        <Button
          size="sm"
          className="bg-purple-600 hover:bg-purple-700"
          onClick={handleSubmit}
          disabled={creating || !agentId}
        >
          {creating ? (
            <Loader2 size={14} className="mr-1.5 animate-spin" />
          ) : (
            <Rocket size={14} className="mr-1.5" />
          )}
          Deploy
        </Button>
        <Button size="sm" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </div>
  );
}
