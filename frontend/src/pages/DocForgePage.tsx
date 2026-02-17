import { FileStack, FileText, Layers, Braces, Database, Cpu, Clock } from "lucide-react";

const PIPELINE_STAGES = [
  { icon: FileText, title: "Multi-Format Parsing", desc: "Supports PDF, DOCX, Markdown, CSV, TXT, and HTML. Extracts text with structure preservation including headers, tables, and metadata." },
  { icon: Layers, title: "Intelligent Chunking", desc: "Semantic-aware chunking with configurable overlap. Supports fixed-size, sentence-based, and recursive splitting strategies." },
  { icon: Braces, title: "Embedding Generation", desc: "Generate vector embeddings using configurable models. Supports OpenAI, Cohere, and local embedding models for privacy-sensitive workloads." },
  { icon: Database, title: "Vector Indexing", desc: "Index chunks into vector databases for efficient retrieval. Compatible with Qdrant, Pinecone, Weaviate, and ChromaDB." },
];

export function DocForgePage() {
  return (
    <div className="p-6">
      <div className="mb-4 flex items-center gap-3">
        <FileStack size={24} className="text-purple-400" />
        <h1 className="text-2xl font-bold text-white">DocForge</h1>
      </div>
      <p className="mb-6 text-gray-400">
        Document ingestion pipeline for RAG knowledge bases. Parses, chunks, embeds, and indexes documents at scale.
      </p>

      {/* Celery Worker Notice */}
      <div className="mb-8 rounded-lg border border-purple-500/30 bg-purple-500/5 p-5">
        <div className="mb-3 flex items-center gap-2">
          <Cpu size={18} className="text-purple-400" />
          <h2 className="text-sm font-semibold text-purple-300">Background Processing Pipeline</h2>
        </div>
        <p className="mb-2 text-sm text-gray-300">
          DocForge runs as a Celery worker for asynchronous document processing. Documents are submitted via the agent builder
          or API, then processed through the pipeline stages below.
        </p>
        <div className="flex items-center gap-2 rounded-md bg-[#0f1117] p-3">
          <Clock size={14} className="text-gray-500" />
          <code className="text-sm text-green-400">celery -A docforge.worker worker --loglevel=info</code>
        </div>
      </div>

      {/* Pipeline Stages */}
      <h2 className="mb-4 text-sm font-semibold text-white uppercase tracking-wider">Pipeline Stages</h2>
      <div className="mb-8 grid grid-cols-1 gap-4 sm:grid-cols-2">
        {PIPELINE_STAGES.map((stage, i) => {
          const Icon = stage.icon;
          return (
            <div key={stage.title} className="rounded-lg border border-[#2a2d37] bg-[#1a1d27] p-4">
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

      {/* Supported Formats */}
      <div className="rounded-lg border border-[#2a2d37] bg-[#1a1d27] p-5">
        <h3 className="mb-3 text-sm font-semibold text-white">Supported Formats</h3>
        <div className="flex flex-wrap gap-2">
          {["PDF", "DOCX", "Markdown", "CSV", "TXT", "HTML", "JSON", "YAML"].map((fmt) => (
            <span key={fmt} className="rounded-full border border-[#2a2d37] bg-white/5 px-3 py-1 text-xs text-gray-300">
              {fmt}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
