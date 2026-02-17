import { useState } from "react";
import { Download } from "lucide-react";
import { Button } from "@/components/ui/Button";

interface ExportButtonProps {
  onExport: (format: "csv" | "pdf") => Promise<void>;
}

export function ExportButton({ onExport }: ExportButtonProps) {
  const [exporting, setExporting] = useState(false);
  const [showDropdown, setShowDropdown] = useState(false);

  async function handleExport(format: "csv" | "pdf") {
    setExporting(true);
    setShowDropdown(false);
    try {
      await onExport(format);
    } finally {
      setExporting(false);
    }
  }

  return (
    <div className="relative">
      <Button
        size="sm"
        variant="outline"
        onClick={() => setShowDropdown(!showDropdown)}
        disabled={exporting}
      >
        <Download size={14} className="mr-1.5" />
        {exporting ? "Exporting…" : "Export"}
      </Button>
      {showDropdown && (
        <div className="absolute right-0 top-full z-10 mt-1 w-32 rounded-md border border-[#2a2d37] bg-[#1a1d27] py-1 shadow-lg">
          <button
            onClick={() => handleExport("csv")}
            className="block w-full px-3 py-1.5 text-left text-sm text-gray-300 hover:bg-white/5"
          >
            Export CSV
          </button>
          <button
            onClick={() => handleExport("pdf")}
            className="block w-full px-3 py-1.5 text-left text-sm text-gray-300 hover:bg-white/5"
          >
            Export PDF
          </button>
        </div>
      )}
    </div>
  );
}
