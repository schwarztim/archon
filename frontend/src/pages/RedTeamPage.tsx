import { useState } from "react";
import { Swords, Terminal, Shield, AlertTriangle, Zap, Bug, Brain, Loader2, Play, ChevronDown, ChevronUp } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { useStartScan, useScanResult } from "@/hooks/useRedTeam";

const CAPABILITIES = [
  { icon: Zap, title: "Prompt Injection Testing", desc: "Test for prompt manipulation attacks including direct injection, indirect injection, and context manipulation." },
  { icon: Bug, title: "Jailbreak Detection", desc: "Attempt to bypass safety guardrails using known jailbreak techniques like DAN, persona-based attacks, and encoding tricks." },
  { icon: Shield, title: "Data Exfiltration Probes", desc: "Try to extract training data, system prompts, or secrets through various extraction techniques." },
  { icon: Brain, title: "Bias & Toxicity Assessment", desc: "Probe for biased, discriminatory, or toxic content generation across multiple dimensions." },
  { icon: AlertTriangle, title: "Adversarial Robustness", desc: "Evaluate model robustness against adversarial inputs, edge cases, and malformed requests." },
];

const ATTACK_TYPES = [
  "prompt_injection",
  "jailbreak",
  "data_exfiltration",
  "bias_toxicity",
  "adversarial",
];

export function RedTeamPage() {
  const [agentId, setAgentId] = useState("");
  const [scanName, setScanName] = useState("");
  const [selectedAttacks, setSelectedAttacks] = useState<string[]>(["prompt_injection"]);
  const [activeScanId, setActiveScanId] = useState<string | null>(null);
  const [showCapabilities, setShowCapabilities] = useState(true);

  const startScan = useStartScan();
  const { data: scanResult, isLoading: scanLoading } = useScanResult(activeScanId);

  const handleStartScan = () => {
    if (!agentId.trim() || selectedAttacks.length === 0) return;
    startScan.mutate(
      {
        agent_id: agentId,
        attack_types: selectedAttacks,
        name: scanName || undefined,
      },
      {
        onSuccess: (data) => {
          setActiveScanId(data.data.id);
        },
      },
    );
  };

  const toggleAttack = (attack: string) => {
    setSelectedAttacks((prev) =>
      prev.includes(attack)
        ? prev.filter((a) => a !== attack)
        : [...prev, attack],
    );
  };

  const result = scanResult?.data;

  return (
    <div className="p-6">
      <div className="mb-4 flex items-center gap-3">
        <Swords size={24} className="text-purple-400" />
        <h1 className="text-2xl font-bold text-white">Red Team Testing</h1>
      </div>
      <p className="mb-6 text-gray-400">
        Run adversarial testing campaigns against your agents to identify vulnerabilities and prompt injection risks.
      </p>

      {/* New Scan Form */}
      <div className="mb-8 rounded-lg border border-purple-500/30 bg-purple-500/5 p-5">
        <div className="mb-3 flex items-center gap-2">
          <Terminal size={18} className="text-purple-400" />
          <h2 className="text-sm font-semibold text-purple-300">New Security Scan</h2>
        </div>

        <div className="mb-4 grid gap-4 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor="agent-id">Target Agent ID</Label>
            <Input
              id="agent-id"
              placeholder="Enter agent ID..."
              value={agentId}
              onChange={(e) => setAgentId(e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="scan-name">Scan Name (optional)</Label>
            <Input
              id="scan-name"
              placeholder="My scan..."
              value={scanName}
              onChange={(e) => setScanName(e.target.value)}
            />
          </div>
        </div>

        <div className="mb-4">
          <Label>Attack Types</Label>
          <div className="mt-2 flex flex-wrap gap-2">
            {ATTACK_TYPES.map((attack) => (
              <button
                key={attack}
                type="button"
                onClick={() => toggleAttack(attack)}
                className={`rounded-full border px-3 py-1 text-xs transition-colors ${
                  selectedAttacks.includes(attack)
                    ? "border-purple-500 bg-purple-500/20 text-purple-300"
                    : "border-surface-border bg-surface-base text-gray-400 hover:border-gray-500"
                }`}
              >
                {attack.replace(/_/g, " ")}
              </button>
            ))}
          </div>
        </div>

        <Button
          size="sm"
          onClick={handleStartScan}
          disabled={startScan.isPending || !agentId.trim() || selectedAttacks.length === 0}
        >
          {startScan.isPending ? (
            <Loader2 size={14} className="mr-1.5 animate-spin" />
          ) : (
            <Play size={14} className="mr-1.5" />
          )}
          Run Security Scan
        </Button>

        {startScan.isError && (
          <p className="mt-2 text-sm text-red-400">Failed to start scan</p>
        )}
      </div>

      {/* Scan Results */}
      {activeScanId && (
        <div className="mb-8 rounded-lg border border-surface-border bg-surface-raised p-5">
          <h2 className="mb-3 text-sm font-semibold text-white">Scan Results</h2>
          {scanLoading ? (
            <div className="flex items-center gap-2 text-sm text-gray-400">
              <Loader2 size={14} className="animate-spin" /> Loading scan results…
            </div>
          ) : result ? (
            <div className="space-y-4">
              <div className="flex flex-wrap gap-4 text-sm">
                {'status' in result && (
                  <span className="text-gray-400">
                    Status:{" "}
                    <span className={`font-medium ${
                      (result as unknown as { status: string }).status === "completed" ? "text-green-400" :
                      (result as unknown as { status: string }).status === "failed" ? "text-red-400" :
                      "text-yellow-400"
                    }`}>
                      {String((result as unknown as { status: string }).status)}
                    </span>
                  </span>
                )}
                <span className="text-gray-400">
                  Total Tests: <span className="font-medium text-white">{result.total_tests}</span>
                </span>
                <span className="text-gray-400">
                  Passed: <span className="font-medium text-green-400">{result.passed}</span>
                </span>
                <span className="text-gray-400">
                  Failed: <span className="font-medium text-red-400">{result.failed}</span>
                </span>
              </div>

              {result.summary && (
                <p className="text-sm text-gray-300">{result.summary}</p>
              )}

              {result.vulnerabilities && result.vulnerabilities.length > 0 && (
                <div className="space-y-2">
                  <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-400">Vulnerabilities</h3>
                  {result.vulnerabilities.map((vuln, i) => (
                    <div
                      key={i}
                      className="rounded-md border border-surface-border bg-surface-base p-3"
                    >
                      <div className="mb-1 flex items-center gap-2">
                        <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                          vuln.severity === "critical" ? "bg-red-500/20 text-red-400" :
                          vuln.severity === "high" ? "bg-orange-500/20 text-orange-400" :
                          vuln.severity === "medium" ? "bg-yellow-500/20 text-yellow-400" :
                          "bg-blue-500/20 text-blue-400"
                        }`}>
                          {vuln.severity}
                        </span>
                        <span className="text-sm font-medium text-white">{vuln.type}</span>
                      </div>
                      <p className="text-xs text-gray-400">{vuln.description}</p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <p className="text-sm text-gray-500">No results available.</p>
          )}
        </div>
      )}

      {/* Capabilities Grid — collapsible */}
      <button
        type="button"
        onClick={() => setShowCapabilities(!showCapabilities)}
        className="mb-4 flex items-center gap-2 text-sm font-semibold text-white uppercase tracking-wider hover:text-purple-300"
      >
        Testing Capabilities
        {showCapabilities ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
      </button>
      {showCapabilities && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {CAPABILITIES.map((cap) => {
            const Icon = cap.icon;
            return (
              <div key={cap.title} className="rounded-lg border border-surface-border bg-surface-raised p-4">
                <div className="mb-2 flex items-center gap-2">
                  <Icon size={16} className="text-purple-400" />
                  <h3 className="text-sm font-semibold text-white">{cap.title}</h3>
                </div>
                <p className="text-xs text-gray-400">{cap.desc}</p>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
