import { useQuery, useMutation } from "@tanstack/react-query";
import { listPolicies, checkGuardrails } from "@/api/dlp";

const GUARDRAIL_POLICIES_KEY = ["guardrail-policies"] as const;

export function useGuardrailPolicies() {
  return useQuery({
    queryKey: [...GUARDRAIL_POLICIES_KEY],
    queryFn: () => listPolicies(),
  });
}

export function useCheckGuardrails() {
  return useMutation({
    mutationFn: (payload: { content: string; direction: string }) =>
      checkGuardrails(payload),
  });
}
