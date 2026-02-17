import { Store } from "lucide-react";
import { PackageCard } from "./PackageCard";
import type { PackageCardData } from "./PackageCard";

interface CatalogGridProps {
  /** Packages to display */
  packages: PackageCardData[];
  /** Called when user clicks Install on a card */
  onInstall: (pkg: PackageCardData) => void;
  /** Whether data is loading */
  isLoading?: boolean;
  /** Empty state hint */
  emptyMessage?: string;
}

/**
 * Grid layout for browsing marketplace packages with loading
 * and empty states.
 */
export function CatalogGrid({
  packages,
  onInstall,
  isLoading = false,
  emptyMessage = "No packages match your search.",
}: CatalogGridProps) {
  if (isLoading) {
    return (
      <div className="flex h-48 items-center justify-center">
        <p className="text-gray-400">Loading marketplace…</p>
      </div>
    );
  }

  if (packages.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center rounded-lg border border-[#2a2d37] bg-[#1a1d27] py-16">
        <Store size={40} className="mb-3 text-gray-600" />
        <p className="text-sm text-gray-500">{emptyMessage}</p>
      </div>
    );
  }

  return (
    <div
      className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4"
      role="list"
      aria-label="Marketplace packages"
    >
      {packages.map((pkg) => (
        <PackageCard
          key={pkg.id ?? pkg.name}
          pkg={pkg}
          onInstall={onInstall}
        />
      ))}
    </div>
  );
}
