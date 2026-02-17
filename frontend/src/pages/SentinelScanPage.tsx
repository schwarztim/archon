import { useState, useEffect, useCallback } from "react";
import {
  Scan,
  Play,
  Loader2,
  AlertTriangle,
} from "lucide-react";
import { Button } from "@/components/ui/Button";
import { apiGet, apiPost } from "@/api/client";
import {
  runDiscoveryScan,
  getPostureScore,
  getRiskBreakdown,
  getServiceInventory,
  getScanHistory,
  remediateFinding,
  bulkRemediate,
} from "@/api/sentinelscan";
import type {
  ServiceFinding,
  PostureScoreResult,
  RiskBreakdownResult,
  ScanHistoryEntry,
} from "@/api/sentinelscan";
import { PostureGauge } from "@/components/sentinelscan/PostureGauge";
import { RiskBars } from "@/components/sentinelscan/RiskBars";
import { ServiceTable } from "@/components/sentinelscan/ServiceTable";
import { ServiceDetail } from "@/components/sentinelscan/ServiceDetail";
import { BulkRemediation } from "@/components/sentinelscan/BulkRemediation";
import { ScanHistory } from "@/components/sentinelscan/ScanHistory";

export function SentinelScanPage() {
  const [services, setServices] = useState<ServiceFinding[]>([]);
  const [posture, setPosture] = useState<PostureScoreResult | null>(null);
  const [risks, setRisks] = useState<RiskBreakdownResult | null>(null);
  const [scanHistory, setScanHistory] = useState<ScanHistoryEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [scanning, setScanning] = useState(false);

  // Detail panel
  const [selectedService, setSelectedService] = useState<ServiceFinding | null>(null);

  // Bulk selection
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());

  // Risk filter
  const [riskFilter, setRiskFilter] = useState<string | null>(null);

  // Scan config
  const [scanSources, setScanSources] = useState<string[]>(["sso", "api_gateway", "dns"]);
  const [scanDepth, setScanDepth] = useState("standard");

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [servicesRes, postureRes, risksRes, historyRes] = await Promise.allSettled([
        getServiceInventory(),
        getPostureScore(),
        getRiskBreakdown(),
        getScanHistory(),
      ]);
      if (servicesRes.status === "fulfilled") {
        const data = servicesRes.value.data;
        setServices(Array.isArray(data) ? data : []);
      }
      if (postureRes.status === "fulfilled") setPosture(postureRes.value.data);
      if (risksRes.status === "fulfilled") setRisks(risksRes.value.data);
      if (historyRes.status === "fulfilled") {
        const data = historyRes.value.data;
        setScanHistory(Array.isArray(data) ? data : []);
      }
    } catch {
      setError("Failed to load SentinelScan data.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void fetchData(); }, [fetchData]);

  async function handleRunScan() {
    setScanning(true);
    setError(null);
    try {
      const res = await runDiscoveryScan({ sources: scanSources, scan_depth: scanDepth });
      if (res.data?.findings) {
        setServices(res.data.findings);
      }
      // Refresh all data after scan
      await fetchData();
    } catch {
      setError("Scan failed. Please try again.");
    } finally {
      setScanning(false);
    }
  }

  async function handleRemediate(findingId: string, action: string) {
    try {
      await remediateFinding(findingId, action);
      setServices((prev) =>
        prev.map((s) =>
          s.id === findingId
            ? { ...s, status: ({ Block: "Blocked", Approve: "Approved", Monitor: "Monitoring", Ignore: "Ignored" } as Record<string, ServiceFinding["status"]>)[action] ?? s.status }
            : s,
        ),
      );
      setSelectedService(null);
    } catch {
      setError("Remediation failed.");
    }
  }

  async function handleBulkRemediate(action: string) {
    try {
      await bulkRemediate(Array.from(selectedIds), action);
      const statusMap: Record<string, ServiceFinding["status"]> = {
        Block: "Blocked", Approve: "Approved", Monitor: "Monitoring", Ignore: "Ignored",
      };
      setServices((prev) =>
        prev.map((s) =>
          selectedIds.has(s.id)
            ? { ...s, status: statusMap[action] ?? s.status }
            : s,
        ),
      );
      setSelectedIds(new Set());
    } catch {
      setError("Bulk remediation failed.");
    }
  }

  async function handleRerunScan(scan: ScanHistoryEntry) {
    setScanning(true);
    try {
      await runDiscoveryScan({ sources: scan.sources, scan_depth: scan.scan_depth });
      await fetchData();
    } catch {
      setError("Re-run failed.");
    } finally {
      setScanning(false);
    }
  }

  function handleToggleSelect(id: string) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function handleSelectAll() {
    if (selectedIds.size === filteredServices.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(filteredServices.map((s) => s.id)));
    }
  }

  function handleSourceToggle(src: string) {
    setScanSources((prev) =>
      prev.includes(src)
        ? prev.filter((s) => s !== src)
        : [...prev, src],
    );
  }

  function handleCategoryClick(category: string) {
    setRiskFilter((prev) => (prev === category ? null : category));
  }

  // Filter services by risk category
  const filteredServices = riskFilter
    ? services.filter((s) => {
        if (riskFilter === "Data Exposure") return ["PII detected", "Confidential data"].includes(s.data_exposure);
        if (riskFilter === "Unauthorized Access") return s.status === "Unapproved";
        if (riskFilter === "Credential Risk") return s.risk_level === "critical";
        if (riskFilter === "Policy Violation") return s.status === "Blocked";
        return true;
      })
    : services;

  if (loading) {
    return <div className="flex h-64 items-center justify-center"><p className="text-gray-400">Loading...</p></div>;
  }

  return (
    <div className="p-6">
      {error && (
        <div className="mb-4 rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">{error}</div>
      )}

      <div className="mb-4 flex items-center gap-3">
        <Scan size={24} className="text-purple-400" />
        <h1 className="text-2xl font-bold text-white">SentinelScan</h1>
      </div>
      <p className="mb-6 text-gray-400">
        Discover shadow AI services, assess security posture, and monitor your organization&apos;s AI landscape.
      </p>

      {/* Top row: Posture Score + Risk Breakdown + Scan Launcher */}
      <div className="mb-8 grid grid-cols-1 gap-4 lg:grid-cols-4">
        {/* Posture Gauge */}
        <PostureGauge posture={posture} serviceCount={services.length} />

        {/* Risk Bars */}
        <RiskBars risks={risks} onCategoryClick={handleCategoryClick} />

        {/* Scan Launcher */}
        <div className="lg:col-span-2 rounded-lg border border-[#2a2d37] bg-[#1a1d27] p-4">
          <h3 className="mb-3 text-xs font-semibold text-gray-400 uppercase tracking-wider">Run Discovery Scan</h3>
          <div className="space-y-3">
            <div>
              <label className="mb-1 block text-xs text-gray-500">Sources</label>
              <div className="flex flex-wrap gap-2">
                {["sso", "api_gateway", "dns"].map((src) => (
                  <button
                    key={src}
                    type="button"
                    className={`rounded-md px-3 py-1 text-xs font-medium transition-colors ${
                      scanSources.includes(src)
                        ? "bg-purple-500/20 text-purple-400 border border-purple-500/40"
                        : "bg-white/5 text-gray-500 border border-[#2a2d37]"
                    }`}
                    onClick={() => handleSourceToggle(src)}
                  >
                    {src.replace("_", " ")}
                  </button>
                ))}
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="mb-1 block text-xs text-gray-500">Scan Depth</label>
                <select
                  className="w-full rounded-md border border-[#2a2d37] bg-[#0f1117] px-3 py-1.5 text-sm text-gray-200 focus:border-purple-500 focus:outline-none"
                  value={scanDepth}
                  onChange={(e) => setScanDepth(e.target.value)}
                >
                  <option value="quick">Quick</option>
                  <option value="standard">Standard</option>
                  <option value="deep">Deep</option>
                </select>
              </div>
              <div className="flex items-end">
                <Button
                  className="w-full"
                  size="sm"
                  onClick={handleRunScan}
                  disabled={scanning || scanSources.length === 0}
                >
                  {scanning ? <Loader2 size={14} className="mr-1.5 animate-spin" /> : <Play size={14} className="mr-1.5" />}
                  Start Scan
                </Button>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Risk filter indicator */}
      {riskFilter && (
        <div className="mb-4 flex items-center gap-2">
          <AlertTriangle size={14} className="text-yellow-400" />
          <span className="text-sm text-gray-400">
            Filtering by: <span className="text-white font-medium">{riskFilter}</span>
          </span>
          <button
            type="button"
            className="text-xs text-purple-400 hover:text-purple-300"
            onClick={() => setRiskFilter(null)}
          >
            Clear filter
          </button>
        </div>
      )}

      {/* Bulk Remediation Bar */}
      <div className="mb-4">
        <BulkRemediation selectedCount={selectedIds.size} onApply={handleBulkRemediate} />
      </div>

      {/* Service Inventory Table */}
      <div className="mb-8">
        <ServiceTable
          services={filteredServices}
          onServiceClick={setSelectedService}
          selectedIds={selectedIds}
          onToggleSelect={handleToggleSelect}
          onSelectAll={handleSelectAll}
        />
      </div>

      {/* Scan History */}
      <ScanHistory scans={scanHistory} onRerun={handleRerunScan} />

      {/* Service Detail Side Panel */}
      {selectedService && (
        <ServiceDetail
          service={selectedService}
          onClose={() => setSelectedService(null)}
          onRemediate={handleRemediate}
        />
      )}
    </div>
  );
}
