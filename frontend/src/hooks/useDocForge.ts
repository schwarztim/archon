import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  listDocuments,
  getDocument,
  ingestDocument,
  deleteDocument,
  reprocessDocument,
  searchDocuments,
  listCollections,
  createCollection,
} from "@/api/docforge";

const DOCUMENTS_KEY = ["documents"] as const;
const COLLECTIONS_KEY = ["collections"] as const;

export function useDocuments(limit = 50, offset = 0) {
  return useQuery({
    queryKey: [...DOCUMENTS_KEY, limit, offset],
    queryFn: () => listDocuments({ limit, offset }),
  });
}

export function useDocument(id: string | null) {
  return useQuery({
    queryKey: [...DOCUMENTS_KEY, id],
    queryFn: () => getDocument(id!),
    enabled: !!id,
  });
}

export function useIngestDocument() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: {
      name: string;
      content: string;
      collection_id?: string;
      metadata?: Record<string, unknown>;
    }) => ingestDocument(payload),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: DOCUMENTS_KEY });
    },
  });
}

export function useDeleteDocument() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => deleteDocument(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: DOCUMENTS_KEY });
    },
  });
}

export function useReprocessDocument() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => reprocessDocument(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: DOCUMENTS_KEY });
    },
  });
}

export function useSearchDocuments() {
  return useMutation({
    mutationFn: (payload: { query: string; collection_id?: string; limit?: number }) =>
      searchDocuments(payload),
  });
}

export function useCollections() {
  return useQuery({
    queryKey: [...COLLECTIONS_KEY],
    queryFn: () => listCollections(),
  });
}

export function useCreateCollection() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: { name: string; description?: string }) =>
      createCollection(payload),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: COLLECTIONS_KEY });
    },
  });
}
