import { ShieldCheck, ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/Button";

export function GuardrailsPage() {
  return (
    <div className="p-6">
      <div className="mb-4 flex items-center gap-3">
        <ShieldCheck size={24} className="text-purple-400" />
        <h1 className="text-2xl font-bold text-white">Guardrails</h1>
      </div>

      <div className="rounded-lg border border-[#2a2d37] bg-[#1a1d27] p-8 text-center">
        <ShieldCheck size={48} className="mx-auto mb-4 text-purple-400" />
        <h2 className="mb-2 text-lg font-semibold text-white">Guardrails are configured via DLP Policies</h2>
        <p className="mb-6 text-sm text-gray-400">
          Content filtering, bias detection, and hallucination checks are managed through the Data Loss Prevention module.
          Configure your guardrail rules, sensitivity levels, and enforcement actions in DLP Policies.
        </p>
        <a href="/dlp">
          <Button size="sm">
            <ArrowRight size={14} className="mr-1.5" />
            Go to DLP Policies
          </Button>
        </a>
      </div>
    </div>
  );
}
