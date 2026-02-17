import { Download } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { useState, useCallback } from "react";

interface Props {
  /** Extra query params to append to the export URL */
  queryParams?: Record<string, string>;
}

export function ExportButton({ queryParams }: Props) {
  const [format, setFormat] = useState<"csv" | "json">("csv");

  const handleExport = useCallback(() => {
    const params = new URLSearchParams({
      format,
      limit: "10000",
      ...(queryParams ?? {}),
    });
    const link = document.createElement("a");
    link.href = `/api/v1/audit-logs/export?${params.toString()}`;
    link.download = `audit_logs.${format}`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  }, [format, queryParams]);

  return (
    <div className="flex items-center gap-2">
      <select
        value={format}
        onChange={(e) => setFormat(e.target.value as "csv" | "json")}
        className="h-8 rounded-md border border-[#2a2d37] bg-[#1a1d27] px-2 text-xs text-gray-300 focus:border-purple-500 focus:outline-none"
      >
        <option value="csv">CSV</option>
        <option value="json">JSON</option>
      </select>
      <Button variant="secondary" size="sm" onClick={handleExport}>
        <Download size={14} className="mr-1.5" />
        Export
      </Button>
    </div>
  );
}
