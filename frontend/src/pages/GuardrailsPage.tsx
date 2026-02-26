import { useState } from "react";
import {
  ShieldCheck,
  ArrowRight,
  Loader2,
  Play,
  Shield,
} from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Textarea } from "@/components/ui/Textarea";
import { Label } from "@/components/ui/Label";
import { useGuardrailPolicies, useCheckGuardrails } from "@/hooks/useGuardrails";

export function GuardrailsPage() {
  const { data: policiesData, isLoading: policiesLoading, error: policiesError } = useGuardrailPolicies();
  const checkGuardrails = useCheckGuardrails();

  const [content, setContent] = useState("");
  const [direction, setDirection] = useState("outbound");

  const policies = policiesData?.data ?? [];

  const handleCheck = () => {
    if (!content.trim()) return;
    checkGuardrails.mutate({ content, direction });
  };

  const result = checkGuardrails.data?.data as Record<string, unknown> | undefined;

  return (
    <div className="p-6">
      <div className="mb-4 flex items-center gap-3">
        <ShieldCheck size={24} className="text-purple-400" />
        <h1 className="text-2xl font-bold text-white">Guardrails</h1>
      </div>
      <p className="mb-6 text-gray-400">
        Content filtering, bias detection, and hallucination checks powered by DLP policies.
      </p>

      {/* Check Content Form */}
      <div className="mb-8 rounded-lg border border-purple-500/30 bg-purple-500/5 p-5">
        <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold text-purple-300">
          <Shield size={16} />
          Check Content Against Guardrails
        </h2>
        <div className="mb-3 space-y-3">
          <div className="space-y-1.5">
            <Label htmlFor="guardrail-content">Content</Label>
            <Textarea
              id="guardrail-content"
              placeholder="Enter text to check..."
              rows={4}
              value={content}
              onChange={(e) => setContent(e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="guardrail-direction">Direction</Label>
            <select
              id="guardrail-direction"
              value={direction}
              onChange={(e) => setDirection(e.target.value)}
              className="flex h-9 w-full max-w-xs rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            >
              <option value="inbound">Inbound (user input)</option>
              <option value="outbound">Outbound (model output)</option>
            </select>
          </div>
        </div>
        <Button
          size="sm"
          onClick={handleCheck}
          disabled={checkGuardrails.isPending || !content.trim()}
        >
          {checkGuardrails.isPending ? (
            <Loader2 size={14} className="mr-1.5 animate-spin" />
          ) : (
            <Play size={14} className="mr-1.5" />
          )}
          Check Guardrails
        </Button>

        {checkGuardrails.isError && (
          <p className="mt-2 text-sm text-red-400">Guardrail check failed</p>
        )}

        {result && (
          <div className="mt-4 rounded-md border border-surface-border bg-surface-base p-4">
            <h3 className="mb-2 text-sm font-semibold text-white">Result</h3>
            <pre className="overflow-auto text-xs text-gray-300">
              {JSON.stringify(result, null, 2)}
            </pre>
          </div>
        )}
      </div>

      {/* Guardrail Policies List */}
      <div className="mb-8 rounded-lg border border-surface-border bg-surface-raised p-5">
        <h2 className="mb-3 text-sm font-semibold text-white">Active Guardrail Policies</h2>
        {policiesLoading ? (
          <div className="flex items-center gap-2 text-sm text-gray-400">
            <Loader2 size={14} className="animate-spin" /> Loading policies…
          </div>
        ) : policiesError ? (
          <div className="rounded-lg border border-red-500/20 bg-red-500/5 p-4 text-sm text-red-400">
            Failed to load policies
          </div>
        ) : policies.length === 0 ? (
          <p className="text-sm text-gray-500">No guardrail policies configured.</p>
        ) : (
          <div className="space-y-2">
            {policies.map((policy) => (
              <div
                key={policy.id}
                className="flex items-center justify-between rounded-md border border-surface-border bg-surface-base px-4 py-3"
              >
                <div>
                  <span className="text-sm font-medium text-white">{policy.name}</span>
                  {policy.description && (
                    <p className="text-xs text-gray-500">{policy.description}</p>
                  )}
                  <div className="mt-1 flex flex-wrap gap-1">
                    {policy.entity_types.map((et) => (
                      <span
                        key={et}
                        className="rounded-full bg-purple-500/10 px-2 py-0.5 text-xs text-purple-300"
                      >
                        {et}
                      </span>
                    ))}
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                    policy.is_active
                      ? "bg-green-500/10 text-green-400"
                      : "bg-gray-500/10 text-gray-400"
                  }`}>
                    {policy.is_active ? "Active" : "Inactive"}
                  </span>
                  <span className="rounded-full bg-orange-500/10 px-2 py-0.5 text-xs font-medium text-orange-300">
                    {policy.action}
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* DLP Link */}
      <div className="rounded-lg border border-surface-border bg-surface-raised p-8 text-center">
        <ShieldCheck size={36} className="mx-auto mb-3 text-purple-400" />
        <h2 className="mb-2 text-sm font-semibold text-white">Manage Guardrail Rules in DLP</h2>
        <p className="mb-4 text-xs text-gray-400">
          Create and configure detailed guardrail rules, sensitivity levels, and enforcement actions in the DLP module.
        </p>
        <a href="/dlp">
          <Button variant="secondary" size="sm">
            <ArrowRight size={14} className="mr-1.5" />
            Go to DLP Policies
          </Button>
        </a>
      </div>
    </div>
  );
}
