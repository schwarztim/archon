// ─── Types ───────────────────────────────────────────────────────────

export interface KnowledgeData {
  enabled: boolean;
  collection: string;
  embeddingModel: string;
  chunkStrategy: string;
  chunkSize: number;
  chunkOverlap: number;
  topK: number;
}

interface KnowledgeStepProps {
  data: KnowledgeData;
  onChange: (data: KnowledgeData) => void;
}

// ─── Constants ───────────────────────────────────────────────────────

const EMBEDDING_MODELS = [
  { value: "text-embedding-3-small", label: "OpenAI text-embedding-3-small", provider: "OpenAI" },
  { value: "text-embedding-3-large", label: "OpenAI text-embedding-3-large", provider: "OpenAI" },
  { value: "text-embedding-ada-002", label: "OpenAI Ada 002", provider: "OpenAI" },
  { value: "voyage-3", label: "Voyage 3", provider: "Voyage" },
  { value: "cohere-embed-v3", label: "Cohere Embed v3", provider: "Cohere" },
];

const CHUNK_STRATEGIES = [
  { value: "fixed", label: "Fixed Size", description: "Split into fixed-size chunks" },
  { value: "semantic", label: "Semantic", description: "Split by semantic boundaries" },
  { value: "recursive", label: "Recursive", description: "Recursively split by separators" },
  { value: "sentence", label: "Sentence", description: "Split by sentence boundaries" },
];

const inputClass =
  "w-full rounded-lg border border-surface-border bg-surface-raised px-3 py-2 text-sm text-white placeholder-gray-500 focus:border-purple-500 focus:outline-none";
const labelClass = "mb-1 block text-xs font-medium text-gray-400";

// ─── Component ───────────────────────────────────────────────────────

export function KnowledgeStep({ data, onChange }: KnowledgeStepProps) {
  return (
    <div className="space-y-4">
      {/* Enable Toggle */}
      <div className="flex items-center justify-between rounded-lg border border-surface-border bg-surface-raised p-4">
        <div>
          <p className="text-sm font-medium text-white">Enable RAG / Knowledge Base</p>
          <p className="text-xs text-gray-500">Connect your agent to a knowledge collection for retrieval-augmented generation</p>
        </div>
        <button
          type="button"
          onClick={() => onChange({ ...data, enabled: !data.enabled })}
          className={`relative h-6 w-11 rounded-full transition-colors ${
            data.enabled ? "bg-purple-600" : "bg-gray-700"
          }`}
        >
          <span
            className={`absolute left-0.5 top-0.5 h-5 w-5 rounded-full bg-white transition-transform ${
              data.enabled ? "translate-x-5" : ""
            }`}
          />
        </button>
      </div>

      {data.enabled && (
        <>
          {/* Collection */}
          <div>
            <label className={labelClass}>Collection Name</label>
            <input
              type="text"
              value={data.collection}
              onChange={(e) => onChange({ ...data, collection: e.target.value })}
              className={inputClass}
              placeholder="my-knowledge-base"
            />
          </div>

          {/* Embedding Model */}
          <div>
            <label className={labelClass}>Embedding Model</label>
            <div className="grid gap-2 sm:grid-cols-2">
              {EMBEDDING_MODELS.map((m) => (
                <button
                  key={m.value}
                  type="button"
                  onClick={() => onChange({ ...data, embeddingModel: m.value })}
                  className={`rounded-lg border p-3 text-left text-sm transition-colors ${
                    data.embeddingModel === m.value
                      ? "border-purple-500 bg-purple-500/10"
                      : "border-surface-border bg-surface-raised hover:border-gray-600"
                  }`}
                >
                  <span className="font-medium text-white">{m.label}</span>
                  <p className="text-xs text-gray-500">{m.provider}</p>
                </button>
              ))}
            </div>
          </div>

          {/* Chunk Strategy */}
          <div>
            <label className={labelClass}>Chunk Strategy</label>
            <div className="grid gap-2 sm:grid-cols-2">
              {CHUNK_STRATEGIES.map((s) => (
                <button
                  key={s.value}
                  type="button"
                  onClick={() => onChange({ ...data, chunkStrategy: s.value })}
                  className={`rounded-lg border p-3 text-left text-sm transition-colors ${
                    data.chunkStrategy === s.value
                      ? "border-purple-500 bg-purple-500/10"
                      : "border-surface-border bg-surface-raised hover:border-gray-600"
                  }`}
                >
                  <span className="font-medium text-white">{s.label}</span>
                  <p className="text-xs text-gray-500">{s.description}</p>
                </button>
              ))}
            </div>
          </div>

          {/* Chunk Size & Overlap */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className={labelClass}>Chunk Size (tokens)</label>
              <input
                type="number"
                min={64}
                max={8192}
                value={data.chunkSize}
                onChange={(e) => onChange({ ...data, chunkSize: parseInt(e.target.value, 10) || 512 })}
                className={inputClass}
              />
            </div>
            <div>
              <label className={labelClass}>Chunk Overlap (tokens)</label>
              <input
                type="number"
                min={0}
                max={1024}
                value={data.chunkOverlap}
                onChange={(e) => onChange({ ...data, chunkOverlap: parseInt(e.target.value, 10) || 50 })}
                className={inputClass}
              />
            </div>
          </div>

          {/* Top-K Slider */}
          <div>
            <label className={labelClass}>Top-K Results: {data.topK}</label>
            <input
              type="range"
              min={1}
              max={20}
              step={1}
              value={data.topK}
              onChange={(e) => onChange({ ...data, topK: parseInt(e.target.value, 10) })}
              className="w-full accent-purple-500"
            />
            <div className="flex justify-between text-xs text-gray-600">
              <span>Fewer (precise)</span>
              <span>More (broad)</span>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
