import { Star, Download, ShieldCheck, Bot } from "lucide-react";
import { Button } from "@/components/ui/Button";

export interface PackageCardData {
  id?: string;
  name: string;
  description: string;
  category: string;
  tags: string[];
  version: string;
  publisher: string;
  downloads: number;
  rating: number;
  verified?: boolean;
  icon?: typeof Bot;
}

interface PackageCardProps {
  pkg: PackageCardData;
  onInstall: (pkg: PackageCardData) => void;
}

function Stars({ rating }: { rating: number }) {
  return (
    <span className="inline-flex items-center gap-0.5">
      {Array.from({ length: 5 }, (_, i) => (
        <Star
          key={i}
          size={12}
          className={
            i < Math.round(rating)
              ? "fill-yellow-400 text-yellow-400"
              : "text-gray-600"
          }
        />
      ))}
      <span className="ml-1 text-xs text-gray-400">{rating.toFixed(1)}</span>
    </span>
  );
}

function formatDownloads(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

/**
 * Card component for a marketplace package with publisher info,
 * ratings, download count, and install button.
 */
export function PackageCard({ pkg, onInstall }: PackageCardProps) {
  const Icon = pkg.icon ?? Bot;

  return (
    <div
      className="rounded-lg border border-surface-border bg-surface-raised p-4 transition-colors hover:border-purple-500/30"
      role="listitem"
    >
      <div className="mb-3 flex items-start gap-3">
        <div className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-lg bg-purple-500/10">
          <Icon size={20} className="text-purple-400" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <h3 className="truncate text-sm font-semibold text-white">
              {pkg.name}
            </h3>
            {pkg.verified && (
              <ShieldCheck
                size={14}
                className="flex-shrink-0 text-blue-400"
                aria-label="Verified"
              />
            )}
          </div>
          <p className="text-[11px] text-gray-500">
            {pkg.publisher} · v{pkg.version}
          </p>
        </div>
      </div>

      <p className="mb-3 line-clamp-2 text-xs text-gray-400">
        {pkg.description}
      </p>

      <div className="mb-3 flex flex-wrap gap-1">
        {pkg.tags.slice(0, 3).map((t) => (
          <span
            key={t}
            className="rounded bg-white/10 px-1.5 py-0.5 text-[10px] text-gray-400"
          >
            {t}
          </span>
        ))}
      </div>

      <div className="mb-3 flex items-center justify-between text-xs text-gray-500">
        <Stars rating={pkg.rating ?? 0} />
        <span className="flex items-center gap-1">
          <Download size={10} /> {formatDownloads(pkg.downloads ?? 0)}
        </span>
      </div>

      <Button
        size="sm"
        className="w-full bg-purple-600 hover:bg-purple-700"
        onClick={() => onInstall(pkg)}
        aria-label={`Install ${pkg.name}`}
      >
        <Download size={14} className="mr-1.5" /> Install
      </Button>
    </div>
  );
}
