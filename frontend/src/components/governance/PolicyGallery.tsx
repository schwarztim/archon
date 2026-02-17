import { useState } from "react";
import { Shield, FileCheck, ShieldCheck, Scale, Lock, CheckCircle, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { createPolicy } from "@/api/governance";

interface PolicyTemplate {
  id: string;
  name: string;
  framework: string;
  icon: React.ReactNode;
  description: string;
  requirements: string[];
}

const POLICY_TEMPLATES: PolicyTemplate[] = [
  {
    id: "soc2",
    name: "SOC 2",
    framework: "SOC2",
    icon: <Shield size={20} className="text-blue-400" />,
    description: "Service Organization Control 2 — trust service criteria for security, availability, and confidentiality.",
    requirements: [
      "Access control policies enforced",
      "Data encryption at rest and in transit",
      "Audit logging enabled for all actions",
      "Incident response plan documented",
      "Change management process in place",
    ],
  },
  {
    id: "gdpr",
    name: "GDPR",
    framework: "GDPR",
    icon: <FileCheck size={20} className="text-green-400" />,
    description: "General Data Protection Regulation — EU data privacy and protection requirements.",
    requirements: [
      "Data processing agreements in place",
      "Right to erasure (right to be forgotten)",
      "Data portability support",
      "Privacy impact assessment completed",
      "Consent management implemented",
    ],
  },
  {
    id: "hipaa",
    name: "HIPAA",
    framework: "HIPAA",
    icon: <ShieldCheck size={20} className="text-red-400" />,
    description: "Health Insurance Portability and Accountability Act — protected health information safeguards.",
    requirements: [
      "PHI access controls enforced",
      "Encryption of PHI data",
      "Business associate agreements signed",
      "Security risk assessment completed",
      "Breach notification procedures defined",
    ],
  },
  {
    id: "pci-dss",
    name: "PCI-DSS",
    framework: "PCI-DSS",
    icon: <Lock size={20} className="text-orange-400" />,
    description: "Payment Card Industry Data Security Standard — cardholder data protection requirements.",
    requirements: [
      "Firewall configuration standards",
      "Encryption of cardholder data",
      "Vulnerability management program",
      "Strong access control measures",
      "Regular monitoring and testing",
    ],
  },
  {
    id: "iso27001",
    name: "ISO 27001",
    framework: "ISO27001",
    icon: <Shield size={20} className="text-cyan-400" />,
    description: "Information Security Management System — international security standard.",
    requirements: [
      "Risk assessment methodology",
      "Security policy documented",
      "Asset management procedures",
      "Human resource security",
      "Communications security",
    ],
  },
  {
    id: "custom",
    name: "Custom",
    framework: "custom",
    icon: <Scale size={20} className="text-purple-400" />,
    description: "Define your own compliance policy with custom rules and requirements.",
    requirements: ["Define custom requirements below"],
  },
];

interface Props {
  onPolicyCreated: () => void;
}

export function PolicyGallery({ onPolicyCreated }: Props) {
  const [selectedTemplate, setSelectedTemplate] = useState<PolicyTemplate | null>(null);
  const [checkedReqs, setCheckedReqs] = useState<Set<string>>(new Set());
  const [policyName, setPolicyName] = useState("");
  const [creating, setCreating] = useState(false);

  function handleSelectTemplate(t: PolicyTemplate) {
    setSelectedTemplate(t);
    setCheckedReqs(new Set(t.requirements));
    setPolicyName(`${t.name} Policy`);
  }

  function toggleReq(req: string) {
    setCheckedReqs((prev) => {
      const next = new Set(prev);
      if (next.has(req)) next.delete(req);
      else next.add(req);
      return next;
    });
  }

  async function handleCreate() {
    if (!selectedTemplate || !policyName.trim()) return;
    setCreating(true);
    try {
      await createPolicy({
        name: policyName,
        description: selectedTemplate.description,
        type: "custom",
        rules: {
          framework: selectedTemplate.framework,
          requirements: Array.from(checkedReqs),
        },
        enforcement: "enforce",
        is_active: true,
      } as Parameters<typeof createPolicy>[0]);
      setSelectedTemplate(null);
      setPolicyName("");
      setCheckedReqs(new Set());
      onPolicyCreated();
    } catch {
      /* ignore */
    } finally {
      setCreating(false);
    }
  }

  const score = selectedTemplate
    ? Math.round((checkedReqs.size / selectedTemplate.requirements.length) * 100)
    : 0;

  return (
    <div className="rounded-lg border border-[#2a2d37] bg-[#1a1d27]">
      <div className="border-b border-[#2a2d37] px-4 py-3">
        <h2 className="text-sm font-semibold text-white">Policy Template Gallery</h2>
      </div>

      <div className="grid grid-cols-1 gap-4 p-4 sm:grid-cols-2 lg:grid-cols-3">
        {POLICY_TEMPLATES.map((t) => (
          <div
            key={t.id}
            className={`cursor-pointer rounded-lg border p-4 transition-colors ${
              selectedTemplate?.id === t.id
                ? "border-purple-500/50 bg-purple-500/10"
                : "border-[#2a2d37] bg-[#0f1117] hover:border-[#3a3d47]"
            }`}
            onClick={() => handleSelectTemplate(t)}
          >
            <div className="mb-2 flex items-center gap-2">
              {t.icon}
              <span className="font-medium text-white">{t.name}</span>
            </div>
            <p className="mb-3 text-xs text-gray-400 line-clamp-2">{t.description}</p>
            <ul className="space-y-1">
              {t.requirements.slice(0, 3).map((r) => (
                <li key={r} className="flex items-start gap-1.5 text-[11px] text-gray-500">
                  <CheckCircle size={10} className="mt-0.5 shrink-0 text-gray-600" />
                  {r}
                </li>
              ))}
              {t.requirements.length > 3 && (
                <li className="text-[11px] text-gray-600">+{t.requirements.length - 3} more…</li>
              )}
            </ul>
          </div>
        ))}
      </div>

      {selectedTemplate && (
        <div className="border-t border-[#2a2d37] p-4">
          <div className="mb-3 flex items-center gap-3">
            <Input
              placeholder="Policy name"
              value={policyName}
              onChange={(e) => setPolicyName(e.target.value)}
              className="max-w-xs"
            />
            <span className="text-sm text-gray-400">
              Score: <span className={score >= 80 ? "text-green-400" : score >= 50 ? "text-yellow-400" : "text-red-400"}>{score}%</span>
            </span>
          </div>
          <div className="mb-3 space-y-2">
            {selectedTemplate.requirements.map((req) => (
              <label key={req} className="flex cursor-pointer items-center gap-2 text-sm text-gray-300">
                <input
                  type="checkbox"
                  checked={checkedReqs.has(req)}
                  onChange={() => toggleReq(req)}
                  className="rounded border-gray-600"
                />
                {req}
              </label>
            ))}
          </div>
          <Button size="sm" onClick={handleCreate} disabled={creating || !policyName.trim()}>
            {creating && <Loader2 size={14} className="mr-1.5 animate-spin" />}
            Create Policy
          </Button>
        </div>
      )}
    </div>
  );
}
