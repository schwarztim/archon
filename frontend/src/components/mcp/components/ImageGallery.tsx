import { useState } from "react";
import { X, ChevronLeft, ChevronRight, ZoomIn } from "lucide-react";
import { cn } from "@/utils/cn";

// ── Types ────────────────────────────────────────────────────────────

interface ImageItem {
  src: string;
  alt?: string;
  caption?: string;
}

interface ImageGalleryProps {
  images: ImageItem[];
  columns?: number;
}

// ── Component ────────────────────────────────────────────────────────

export function ImageGallery({ images, columns = 3 }: ImageGalleryProps) {
  const [lightboxIdx, setLightboxIdx] = useState<number | null>(null);

  function prev() {
    setLightboxIdx((i) =>
      i !== null ? (i - 1 + images.length) % images.length : null,
    );
  }

  function next() {
    setLightboxIdx((i) =>
      i !== null ? (i + 1) % images.length : null,
    );
  }

  return (
    <>
      {/* Grid */}
      <div
        className="grid gap-2 rounded-lg border border-[#2a2d37] bg-[#0f1117] p-3"
        style={{ gridTemplateColumns: `repeat(${columns}, 1fr)` }}
      >
        {images.map((img, i) => (
          <button
            key={i}
            onClick={() => setLightboxIdx(i)}
            className="group relative overflow-hidden rounded-md border border-[#2a2d37] transition-colors hover:border-purple-500/40"
          >
            <img
              src={img.src}
              alt={img.alt ?? `Image ${i + 1}`}
              className="aspect-square w-full object-cover"
              loading="lazy"
            />
            <div className="absolute inset-0 flex items-center justify-center bg-black/0 transition-colors group-hover:bg-black/40">
              <ZoomIn
                size={20}
                className="text-white opacity-0 transition-opacity group-hover:opacity-100"
              />
            </div>
            {img.caption && (
              <p className="absolute bottom-0 w-full truncate bg-black/60 px-2 py-1 text-xs text-gray-300">
                {img.caption}
              </p>
            )}
          </button>
        ))}
      </div>

      {/* Lightbox */}
      {lightboxIdx !== null && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm"
          onClick={() => setLightboxIdx(null)}
        >
          <button
            className="absolute right-4 top-4 rounded-full bg-white/10 p-2 text-white hover:bg-white/20"
            onClick={() => setLightboxIdx(null)}
            aria-label="Close"
          >
            <X size={20} />
          </button>

          <button
            className="absolute left-4 top-1/2 -translate-y-1/2 rounded-full bg-white/10 p-2 text-white hover:bg-white/20"
            onClick={(e) => { e.stopPropagation(); prev(); }}
            aria-label="Previous"
          >
            <ChevronLeft size={24} />
          </button>

          <div className="max-h-[80vh] max-w-[80vw]" onClick={(e) => e.stopPropagation()}>
            <img
              src={images[lightboxIdx].src}
              alt={images[lightboxIdx].alt ?? ""}
              className="max-h-[80vh] max-w-[80vw] rounded-lg object-contain"
            />
            {images[lightboxIdx].caption && (
              <p className="mt-2 text-center text-sm text-gray-400">
                {images[lightboxIdx].caption}
              </p>
            )}
          </div>

          <button
            className="absolute right-4 top-1/2 -translate-y-1/2 rounded-full bg-white/10 p-2 text-white hover:bg-white/20"
            onClick={(e) => { e.stopPropagation(); next(); }}
            aria-label="Next"
          >
            <ChevronRight size={24} />
          </button>

          <p className="absolute bottom-4 text-xs text-gray-500">
            {lightboxIdx + 1} / {images.length}
          </p>
        </div>
      )}
    </>
  );
}
