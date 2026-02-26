import { useState } from "react";
import {
  FileStack,
  FileText,
  Layers,
  Braces,
  Database,
  Cpu,
  Search,
  Upload,
  Trash2,
  RefreshCw,
  Loader2,
  Plus,
  ChevronDown,
  ChevronUp,
  FolderOpen,
} from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { Textarea } from "@/components/ui/Textarea";
import {
  useDocuments,
  useIngestDocument,
  useDeleteDocument,
  useReprocessDocument,
  useSearchDocuments,
  useCollections,
  useCreateCollection,
} from "@/hooks/useDocForge";

const PIPELINE_STAGES = [
  { icon: FileText, title: "Multi-Format Parsing", desc: "Supports PDF, DOCX, Markdown, CSV, TXT, and HTML. Extracts text with structure preservation including headers, tables, and metadata." },
  { icon: Layers, title: "Intelligent Chunking", desc: "Semantic-aware chunking with configurable overlap. Supports fixed-size, sentence-based, and recursive splitting strategies." },
  { icon: Braces, title: "Embedding Generation", desc: "Generate vector embeddings using configurable models. Supports OpenAI, Cohere, and local embedding models for privacy-sensitive workloads." },
  { icon: Database, title: "Vector Indexing", desc: "Index chunks into vector databases for efficient retrieval. Compatible with Qdrant, Pinecone, Weaviate, and ChromaDB." },
];

export function DocForgePage() {
  const [activeTab, setActiveTab] = useState<"documents" | "collections">("documents");
  const [searchQuery, setSearchQuery] = useState("");
  const [showPipeline, setShowPipeline] = useState(false);

  // Ingest form
  const [docName, setDocName] = useState("");
  const [docContent, setDocContent] = useState("");
  const [showIngest, setShowIngest] = useState(false);

  // Collection form
  const [collName, setCollName] = useState("");
  const [collDesc, setCollDesc] = useState("");

  const { data: docsData, isLoading: docsLoading, error: docsError } = useDocuments();
  const { data: collectionsData, isLoading: collectionsLoading } = useCollections();
  const ingestDoc = useIngestDocument();
  const deleteDoc = useDeleteDocument();
  const reprocessDoc = useReprocessDocument();
  const searchDocs = useSearchDocuments();
  const createColl = useCreateCollection();

  const documents = docsData?.data ?? [];
  const collections = collectionsData?.data ?? [];
  const searchResults = searchDocs.data?.data ?? [];

  const handleIngest = () => {
    if (!docName.trim() || !docContent.trim()) return;
    ingestDoc.mutate(
      { name: docName, content: docContent },
      {
        onSuccess: () => {
          setDocName("");
          setDocContent("");
          setShowIngest(false);
        },
      },
    );
  };

  const handleSearch = () => {
    if (!searchQuery.trim()) return;
    searchDocs.mutate({ query: searchQuery, limit: 20 });
  };

  const handleCreateCollection = () => {
    if (!collName.trim()) return;
    createColl.mutate(
      { name: collName, description: collDesc || undefined },
      {
        onSuccess: () => {
          setCollName("");
          setCollDesc("");
        },
      },
    );
  };

  return (
    <div className="p-6">
      <div className="mb-4 flex items-center gap-3">
        <FileStack size={24} className="text-purple-400" />
        <h1 className="text-2xl font-bold text-white">DocForge</h1>
      </div>
      <p className="mb-6 text-gray-400">
        Document ingestion pipeline for RAG knowledge bases. Parses, chunks, embeds, and indexes documents at scale.
      </p>

      {/* Tabs */}
      <div className="mb-6 flex gap-2 border-b border-surface-border pb-2">
        <button
          type="button"
          onClick={() => setActiveTab("documents")}
          className={`rounded-t-md px-4 py-2 text-sm font-medium transition-colors ${
            activeTab === "documents"
              ? "bg-surface-raised text-purple-400"
              : "text-gray-400 hover:text-gray-200"
          }`}
        >
          <FileText size={14} className="mr-1.5 inline" />
          Documents
        </button>
        <button
          type="button"
          onClick={() => setActiveTab("collections")}
          className={`rounded-t-md px-4 py-2 text-sm font-medium transition-colors ${
            activeTab === "collections"
              ? "bg-surface-raised text-purple-400"
              : "text-gray-400 hover:text-gray-200"
          }`}
        >
          <FolderOpen size={14} className="mr-1.5 inline" />
          Collections ({collections.length})
        </button>
      </div>

      {activeTab === "documents" && (
        <div className="space-y-6">
          {/* Search + Upload bar */}
          <div className="flex flex-wrap gap-3">
            <div className="flex flex-1 gap-2">
              <Input
                placeholder="Search documents..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleSearch()}
                className="max-w-md"
              />
              <Button
                variant="secondary"
                size="sm"
                onClick={handleSearch}
                disabled={searchDocs.isPending}
              >
                {searchDocs.isPending ? (
                  <Loader2 size={14} className="mr-1.5 animate-spin" />
                ) : (
                  <Search size={14} className="mr-1.5" />
                )}
                Search
              </Button>
            </div>
            <Button size="sm" onClick={() => setShowIngest(!showIngest)}>
              <Upload size={14} className="mr-1.5" />
              Ingest Document
            </Button>
          </div>

          {/* Ingest form */}
          {showIngest && (
            <div className="rounded-lg border border-purple-500/30 bg-purple-500/5 p-5">
              <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-purple-300">
                <Cpu size={16} /> Ingest New Document
              </h3>
              <div className="mb-3 space-y-3">
                <div className="space-y-1.5">
                  <Label htmlFor="doc-name">Document Name</Label>
                  <Input
                    id="doc-name"
                    placeholder="my-document.pdf"
                    value={docName}
                    onChange={(e) => setDocName(e.target.value)}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="doc-content">Content</Label>
                  <Textarea
                    id="doc-content"
                    placeholder="Paste document content or a URL..."
                    rows={4}
                    value={docContent}
                    onChange={(e) => setDocContent(e.target.value)}
                  />
                </div>
              </div>
              <Button
                size="sm"
                onClick={handleIngest}
                disabled={ingestDoc.isPending || !docName.trim() || !docContent.trim()}
              >
                {ingestDoc.isPending ? (
                  <Loader2 size={14} className="mr-1.5 animate-spin" />
                ) : (
                  <Upload size={14} className="mr-1.5" />
                )}
                Ingest
              </Button>
              {ingestDoc.isError && (
                <p className="mt-2 text-sm text-red-400">Failed to ingest document</p>
              )}
            </div>
          )}

          {/* Search results */}
          {searchDocs.isSuccess && searchResults.length > 0 && (
            <div className="rounded-lg border border-surface-border bg-surface-raised p-5">
              <h3 className="mb-3 text-sm font-semibold text-white">
                Search Results ({searchResults.length})
              </h3>
              <div className="space-y-2">
                {searchResults.map((r) => (
                  <div
                    key={r.id}
                    className="rounded-md border border-surface-border bg-surface-base p-3"
                  >
                    <div className="flex items-center justify-between">
                      <span className="text-sm font-medium text-white">{r.name}</span>
                      <span className="text-xs text-gray-500">
                        score: {r.score.toFixed(3)}
                      </span>
                    </div>
                    <p className="mt-1 text-xs text-gray-400">{r.snippet}</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Document list */}
          <div className="rounded-lg border border-surface-border bg-surface-raised p-5">
            <h3 className="mb-3 text-sm font-semibold text-white">
              All Documents
            </h3>
            {docsLoading ? (
              <div className="flex items-center gap-2 text-sm text-gray-400">
                <Loader2 size={14} className="animate-spin" /> Loading documents…
              </div>
            ) : docsError ? (
              <div className="rounded-lg border border-red-500/20 bg-red-500/5 p-4 text-sm text-red-400">
                Failed to load documents
              </div>
            ) : documents.length === 0 ? (
              <p className="text-sm text-gray-500">No documents ingested yet.</p>
            ) : (
              <div className="space-y-2">
                {documents.map((doc) => (
                  <div
                    key={doc.id}
                    className="flex items-center justify-between rounded-md border border-surface-border bg-surface-base px-3 py-2"
                  >
                    <div>
                      <span className="text-sm font-medium text-white">{doc.name}</span>
                      <span className="ml-2 text-xs text-gray-500">{doc.status}</span>
                      {doc.chunk_count != null && (
                        <span className="ml-2 text-xs text-gray-500">
                          {doc.chunk_count} chunks
                        </span>
                      )}
                    </div>
                    <div className="flex gap-1">
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => reprocessDoc.mutate(doc.id)}
                        title="Reprocess"
                        disabled={reprocessDoc.isPending}
                      >
                        <RefreshCw size={14} />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => deleteDoc.mutate(doc.id)}
                        title="Delete"
                        disabled={deleteDoc.isPending}
                      >
                        <Trash2 size={14} className="text-red-400" />
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {activeTab === "collections" && (
        <div className="space-y-6">
          {/* Create collection */}
          <div className="rounded-lg border border-surface-border bg-surface-raised p-5">
            <h3 className="mb-3 text-sm font-semibold text-white">Create Collection</h3>
            <div className="mb-3 flex flex-wrap gap-3">
              <Input
                placeholder="Collection name..."
                value={collName}
                onChange={(e) => setCollName(e.target.value)}
                className="max-w-xs"
              />
              <Input
                placeholder="Description (optional)"
                value={collDesc}
                onChange={(e) => setCollDesc(e.target.value)}
                className="max-w-sm"
              />
              <Button
                size="sm"
                onClick={handleCreateCollection}
                disabled={createColl.isPending || !collName.trim()}
              >
                {createColl.isPending ? (
                  <Loader2 size={14} className="mr-1.5 animate-spin" />
                ) : (
                  <Plus size={14} className="mr-1.5" />
                )}
                Create
              </Button>
            </div>
            {createColl.isError && (
              <p className="text-sm text-red-400">Failed to create collection</p>
            )}
          </div>

          {/* Collection list */}
          <div className="rounded-lg border border-surface-border bg-surface-raised p-5">
            <h3 className="mb-3 text-sm font-semibold text-white">Collections</h3>
            {collectionsLoading ? (
              <div className="flex items-center gap-2 text-sm text-gray-400">
                <Loader2 size={14} className="animate-spin" /> Loading collections…
              </div>
            ) : collections.length === 0 ? (
              <p className="text-sm text-gray-500">No collections yet.</p>
            ) : (
              <div className="space-y-2">
                {collections.map((coll) => (
                  <div
                    key={coll.id}
                    className="flex items-center justify-between rounded-md border border-surface-border bg-surface-base px-3 py-2"
                  >
                    <div>
                      <span className="text-sm font-medium text-white">{coll.name}</span>
                      {coll.description && (
                        <span className="ml-2 text-xs text-gray-500">{coll.description}</span>
                      )}
                    </div>
                    <span className="text-xs text-gray-500">
                      {coll.document_count ?? 0} docs
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Pipeline Stages — collapsible */}
      <div className="mt-8">
        <button
          type="button"
          onClick={() => setShowPipeline(!showPipeline)}
          className="mb-4 flex items-center gap-2 text-sm font-semibold text-white uppercase tracking-wider hover:text-purple-300"
        >
          Pipeline Stages
          {showPipeline ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        </button>
        {showPipeline && (
          <>
            <div className="mb-8 grid grid-cols-1 gap-4 sm:grid-cols-2">
              {PIPELINE_STAGES.map((stage, i) => {
                const Icon = stage.icon;
                return (
                  <div key={stage.title} className="rounded-lg border border-surface-border bg-surface-raised p-4">
                    <div className="mb-2 flex items-center gap-3">
                      <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-purple-500/10">
                        <Icon size={16} className="text-purple-400" />
                      </div>
                      <div>
                        <span className="mr-2 text-xs text-gray-500">Stage {i + 1}</span>
                        <h3 className="text-sm font-semibold text-white">{stage.title}</h3>
                      </div>
                    </div>
                    <p className="text-xs text-gray-400">{stage.desc}</p>
                  </div>
                );
              })}
            </div>

            <div className="rounded-lg border border-surface-border bg-surface-raised p-5">
              <h3 className="mb-3 text-sm font-semibold text-white">Supported Formats</h3>
              <div className="flex flex-wrap gap-2">
                {["PDF", "DOCX", "Markdown", "CSV", "TXT", "HTML", "JSON", "YAML"].map((fmt) => (
                  <span key={fmt} className="rounded-full border border-surface-border bg-white/5 px-3 py-1 text-xs text-gray-300">
                    {fmt}
                  </span>
                ))}
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
