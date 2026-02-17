import { Swords, Terminal, Shield, AlertTriangle, Zap, Bug, Brain } from "lucide-react";
import { Button } from "@/components/ui/Button";

const CAPABILITIES = [
  { icon: Zap, title: "Prompt Injection Testing", desc: "Test for prompt manipulation attacks including direct injection, indirect injection, and context manipulation." },
  { icon: Bug, title: "Jailbreak Detection", desc: "Attempt to bypass safety guardrails using known jailbreak techniques like DAN, persona-based attacks, and encoding tricks." },
  { icon: Shield, title: "Data Exfiltration Probes", desc: "Try to extract training data, system prompts, or secrets through various extraction techniques." },
  { icon: Brain, title: "Bias & Toxicity Assessment", desc: "Probe for biased, discriminatory, or toxic content generation across multiple dimensions." },
  { icon: AlertTriangle, title: "Adversarial Robustness", desc: "Evaluate model robustness against adversarial inputs, edge cases, and malformed requests." },
];

export function RedTeamPage() {
  return (
    <div className="p-6">
      <div className="mb-4 flex items-center gap-3">
        <Swords size={24} className="text-purple-400" />
        <h1 className="text-2xl font-bold text-white">Red Team Testing</h1>
      </div>
      <p className="mb-6 text-gray-400">
        Run adversarial testing campaigns against your agents to identify vulnerabilities and prompt injection risks.
      </p>

      {/* CLI Notice */}
      <div className="mb-8 rounded-lg border border-purple-500/30 bg-purple-500/5 p-5">
        <div className="mb-3 flex items-center gap-2">
          <Terminal size={18} className="text-purple-400" />
          <h2 className="text-sm font-semibold text-purple-300">CLI-Based Red Team Engine</h2>
        </div>
        <p className="mb-3 text-sm text-gray-300">
          The Red Team engine runs as a standalone CLI tool for security testing. It operates independently from the web API to ensure isolated and controlled adversarial testing environments.
        </p>
        <div className="mb-4 rounded-md bg-[#0f1117] p-3">
          <code className="text-sm text-green-400">python3 -m security.red_team.engine</code>
        </div>
        <Button
          size="sm"
          onClick={() => alert("Red Team Engine runs as a CLI tool. Use: python3 -m security.red_team.engine")}
        >
          <Swords size={14} className="mr-1.5" />
          Run Red Team Assessment
        </Button>
      </div>

      {/* Capabilities Grid */}
      <h2 className="mb-4 text-sm font-semibold text-white uppercase tracking-wider">Testing Capabilities</h2>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {CAPABILITIES.map((cap) => {
          const Icon = cap.icon;
          return (
            <div key={cap.title} className="rounded-lg border border-[#2a2d37] bg-[#1a1d27] p-4">
              <div className="mb-2 flex items-center gap-2">
                <Icon size={16} className="text-purple-400" />
                <h3 className="text-sm font-semibold text-white">{cap.title}</h3>
              </div>
              <p className="text-xs text-gray-400">{cap.desc}</p>
            </div>
          );
        })}
      </div>

      {/* Usage Instructions */}
      <div className="mt-8 rounded-lg border border-[#2a2d37] bg-[#1a1d27] p-5">
        <h3 className="mb-3 text-sm font-semibold text-white">Usage</h3>
        <div className="space-y-2 text-sm text-gray-400">
          <p>1. Configure target agent in <code className="rounded bg-white/10 px-1.5 py-0.5 text-xs text-gray-300">security/red_team/config.yaml</code></p>
          <p>2. Select attack categories to run</p>
          <p>3. Execute: <code className="rounded bg-white/10 px-1.5 py-0.5 text-xs text-green-400">python3 -m security.red_team.engine --target &lt;agent_id&gt; --attacks prompt_injection,jailbreak</code></p>
          <p>4. Review results in the generated report</p>
        </div>
      </div>
    </div>
  );
}
