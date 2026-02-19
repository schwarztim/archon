import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  getSettings,
  updateSettings,
  getFeatureFlags,
  toggleFeatureFlag,
  listApiKeys,
  createApiKey,
  deleteApiKey,
  testNotification,
} from "@/api/settings";
import type { PlatformSettings } from "@/api/settings";

const SETTINGS_KEY = ["settings"] as const;
const FEATURE_FLAGS_KEY = ["settings", "feature-flags"] as const;
const API_KEYS_KEY = ["settings", "api-keys"] as const;

export function useSettings() {
  return useQuery({
    queryKey: [...SETTINGS_KEY],
    queryFn: () => getSettings(),
  });
}

export function useUpdateSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: Partial<PlatformSettings>) => updateSettings(payload),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: SETTINGS_KEY });
    },
  });
}

export function useFeatureFlags() {
  return useQuery({
    queryKey: [...FEATURE_FLAGS_KEY],
    queryFn: () => getFeatureFlags(),
  });
}

export function useToggleFeatureFlag() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ flagName, enabled }: { flagName: string; enabled: boolean }) =>
      toggleFeatureFlag(flagName, enabled),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: FEATURE_FLAGS_KEY });
    },
  });
}

export function useApiKeys() {
  return useQuery({
    queryKey: [...API_KEYS_KEY],
    queryFn: () => listApiKeys(),
  });
}

export function useCreateApiKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: { name: string; scopes: string[] }) => createApiKey(payload),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: API_KEYS_KEY });
    },
  });
}

export function useDeleteApiKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (keyId: string) => deleteApiKey(keyId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: API_KEYS_KEY });
    },
  });
}

export function useTestNotification() {
  return useMutation({
    mutationFn: (payload: { channel: string; recipient?: string }) =>
      testNotification(payload),
  });
}
