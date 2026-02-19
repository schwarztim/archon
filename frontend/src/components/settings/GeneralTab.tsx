import { useState, useEffect } from "react";
import { Info, ExternalLink, Loader2, Save } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { useSettings, useUpdateSettings } from "@/hooks/useSettings";

function Card({
  icon: Icon,
  title,
  children,
}: {
  icon: React.ElementType;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-lg border border-[#2a2d37] bg-[#1a1d27] p-5">
      <h2 className="mb-4 flex items-center gap-2 text-sm font-semibold">
        <Icon size={14} className="text-purple-400" />
        {title}
      </h2>
      {children}
    </div>
  );
}

function InfoRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex gap-2 text-sm">
      <span className="text-gray-400">{label}:</span>
      <span className="text-gray-200">{children}</span>
    </div>
  );
}

export function GeneralTab() {
  const { data, isLoading, error } = useSettings();
  const updateSettings = useUpdateSettings();

  const [platformName, setPlatformName] = useState("Archon");
  const [defaultLang, setDefaultLang] = useState("en");
  const [tz, setTz] = useState("UTC");
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    if (data?.data) {
      setPlatformName(data.data.platform_name ?? "Archon");
      setDefaultLang(data.data.default_language ?? "en");
      setTz(data.data.timezone ?? "UTC");
      setDirty(false);
    }
  }, [data]);

  const markDirty = () => setDirty(true);

  const handleSave = () => {
    updateSettings.mutate({
      platform_name: platformName,
      default_language: defaultLang,
      timezone: tz,
    }, { onSuccess: () => setDirty(false) });
  };

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-sm text-gray-400">
        <Loader2 size={14} className="animate-spin" /> Loading settings…
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-lg border border-red-500/20 bg-red-500/5 p-4 text-sm text-red-400">
        Failed to load settings: {(error as Error).message}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <Card icon={Info} title="Platform">
        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="platform-name">Platform Name</Label>
            <Input
              id="platform-name"
              value={platformName}
              onChange={(e) => { setPlatformName(e.target.value); markDirty(); }}
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="logo-upload">Logo</Label>
            <div className="flex items-center gap-3">
              <div className="flex h-12 w-12 items-center justify-center rounded-lg border border-[#2a2d37] bg-[#0f1117] text-xs text-gray-500">
                Logo
              </div>
              <Button variant="secondary" size="sm" disabled>
                Upload
              </Button>
            </div>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="default-lang">Default Language</Label>
            <select
              id="default-lang"
              value={defaultLang}
              onChange={(e) => { setDefaultLang(e.target.value); markDirty(); }}
              className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            >
              <option value="en">English</option>
              <option value="es">Spanish</option>
              <option value="fr">French</option>
              <option value="de">German</option>
            </select>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="timezone">Timezone</Label>
            <select
              id="timezone"
              value={tz}
              onChange={(e) => { setTz(e.target.value); markDirty(); }}
              className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            >
              <option value="UTC">UTC</option>
              <option value="America/New_York">America/New_York</option>
              <option value="America/Chicago">America/Chicago</option>
              <option value="America/Los_Angeles">America/Los_Angeles</option>
              <option value="Europe/London">Europe/London</option>
              <option value="Asia/Tokyo">Asia/Tokyo</option>
            </select>
          </div>

          <div className="flex items-center gap-3">
            <Button
              size="sm"
              onClick={handleSave}
              disabled={!dirty || updateSettings.isPending}
            >
              {updateSettings.isPending ? (
                <Loader2 size={14} className="mr-1.5 animate-spin" />
              ) : (
                <Save size={14} className="mr-1.5" />
              )}
              Save Changes
            </Button>
            {updateSettings.isSuccess && !dirty && (
              <span className="text-xs text-green-400">Saved</span>
            )}
            {updateSettings.isError && (
              <span className="text-xs text-red-400">Failed to save</span>
            )}
          </div>
        </div>
      </Card>

      <Card icon={Info} title="Platform Info">
        <div className="space-y-2">
          <InfoRow label="Version">
            <span className="font-mono">{data?.data?.version ?? "1.0.0"}</span>
          </InfoRow>
          <InfoRow label="API Prefix">
            <code className="rounded bg-[#2a2d37] px-1.5 py-0.5 text-xs font-mono">{data?.data?.api_prefix ?? "/api/v1"}</code>
          </InfoRow>
        </div>
      </Card>

      <Card icon={ExternalLink} title="Quick Links">
        <div className="flex flex-wrap gap-3">
          <Button variant="secondary" size="sm" onClick={() => window.open("/docs", "_blank")}>
            <ExternalLink size={14} className="mr-1.5" />
            View API Docs
          </Button>
          <Button variant="secondary" size="sm" onClick={() => window.open("/openapi.json", "_blank")}>
            <ExternalLink size={14} className="mr-1.5" />
            View OpenAPI
          </Button>
        </div>
      </Card>
    </div>
  );
}
