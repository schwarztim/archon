import { useState, useEffect, useCallback } from "react";
import {
  Settings,
  Info,
  ExternalLink,
  Server,
  Loader2,
  ShieldCheck,
  Bell,
  Palette,
  RefreshCw,
  Activity,
  Database,
  HardDrive,
  Lock,
  Sun,
  Moon,
} from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";

/* ------------------------------------------------------------------ */
/*  Types                                                             */
/* ------------------------------------------------------------------ */

interface HealthData {
  status: string;
  version?: string;
}

interface ServiceCheck {
  status: string;
  error?: string;
}

interface ReadinessData {
  status: string;
  version?: string;
  checks: {
    database: ServiceCheck;
    redis: ServiceCheck;
    vault: ServiceCheck;
  };
  timestamp?: string;
}

type SsoProtocol = "oidc" | "saml";

/* ------------------------------------------------------------------ */
/*  Helpers                                                           */
/* ------------------------------------------------------------------ */

function StatusBadge({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ${
        ok ? "bg-green-500/10 text-green-400" : "bg-red-500/10 text-red-400"
      }`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${ok ? "bg-green-400" : "bg-red-400"}`} />
      {label}
    </span>
  );
}

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

/* ------------------------------------------------------------------ */
/*  Tab: General                                                      */
/* ------------------------------------------------------------------ */

function GeneralTab() {
  return (
    <div className="space-y-6">
      <Card icon={Info} title="Platform">
        <div className="space-y-2">
          <InfoRow label="Platform">Archon</InfoRow>
          <InfoRow label="Version">
            <span className="font-mono">1.0.0</span>
          </InfoRow>
          <InfoRow label="API Prefix">
            <code className="rounded bg-[#2a2d37] px-1.5 py-0.5 text-xs font-mono">/api/v1</code>
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

/* ------------------------------------------------------------------ */
/*  Tab: Authentication                                               */
/* ------------------------------------------------------------------ */

function AuthenticationTab() {
  const [protocol, setProtocol] = useState<SsoProtocol>("oidc");
  const [discoveryUrl, setDiscoveryUrl] = useState("");
  const [clientId, setClientId] = useState("");
  const [redirectUri, setRedirectUri] = useState(
    `${window.location.origin}/callback`,
  );

  return (
    <Card icon={ShieldCheck} title="SSO Configuration">
      <p className="mb-5 text-sm text-gray-400">
        Configure your OIDC/SAML identity provider.
      </p>

      <div className="space-y-4">
        {/* Protocol */}
        <div className="space-y-1.5">
          <Label htmlFor="sso-protocol">Protocol</Label>
          <select
            id="sso-protocol"
            value={protocol}
            onChange={(e) => setProtocol(e.target.value as SsoProtocol)}
            className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          >
            <option value="oidc">OIDC (OpenID Connect)</option>
            <option value="saml">SAML 2.0</option>
          </select>
        </div>

        {/* Discovery URL */}
        <div className="space-y-1.5">
          <Label htmlFor="sso-discovery">Discovery URL</Label>
          <Input
            id="sso-discovery"
            placeholder="https://idp.example.com/.well-known/openid-configuration"
            value={discoveryUrl}
            onChange={(e) => setDiscoveryUrl(e.target.value)}
          />
        </div>

        {/* Client ID */}
        <div className="space-y-1.5">
          <Label htmlFor="sso-client-id">Client ID</Label>
          <Input
            id="sso-client-id"
            placeholder="archon-platform"
            value={clientId}
            onChange={(e) => setClientId(e.target.value)}
          />
        </div>

        {/* Redirect URI */}
        <div className="space-y-1.5">
          <Label htmlFor="sso-redirect">Redirect URI</Label>
          <Input
            id="sso-redirect"
            value={redirectUri}
            onChange={(e) => setRedirectUri(e.target.value)}
          />
        </div>

        {/* Actions */}
        <div className="flex gap-3 pt-2">
          <Button disabled>
            Test Connection
          </Button>
          <Button variant="secondary" disabled>
            Save
          </Button>
        </div>
      </div>
    </Card>
  );
}

/* ------------------------------------------------------------------ */
/*  Tab: System Health                                                */
/* ------------------------------------------------------------------ */

function SystemHealthTab() {
  const [health, setHealth] = useState<HealthData | null>(null);
  const [readiness, setReadiness] = useState<ReadinessData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchHealth = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const [hRes, rRes] = await Promise.allSettled([
        fetch("/api/v1/health", { credentials: "include" }),
        fetch("/ready", { credentials: "include" }),
      ]);

      if (hRes.status === "fulfilled" && hRes.value.ok) {
        setHealth(await hRes.value.json() as HealthData);
      } else {
        setHealth(null);
      }

      if (rRes.status === "fulfilled" && rRes.value.ok) {
        setReadiness(await rRes.value.json() as ReadinessData);
      } else {
        setReadiness(null);
      }

      // If both failed, show an error
      if (
        (hRes.status === "rejected" || !hRes.value.ok) &&
        (rRes.status === "rejected" || !rRes.value.ok)
      ) {
        const msg =
          hRes.status === "rejected"
            ? (hRes.reason as Error).message
            : hRes.value.statusText;
        setError(`Failed to reach health endpoints: ${msg}`);
      }
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchHealth();
  }, [fetchHealth]);

  const services: {
    name: string;
    icon: React.ElementType;
    status: string | undefined;
  }[] = [
    {
      name: "API",
      icon: Activity,
      status: health?.status,
    },
    {
      name: "Database",
      icon: Database,
      status: readiness?.checks?.database?.status,
    },
    {
      name: "Redis",
      icon: HardDrive,
      status: readiness?.checks?.redis?.status,
    },
    {
      name: "Vault",
      icon: Lock,
      status: readiness?.checks?.vault?.status,
    },
  ];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-gray-400">Service Status</h3>
        <Button variant="ghost" size="sm" onClick={() => void fetchHealth()} disabled={loading}>
          <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
          <span className="ml-1.5">Refresh</span>
        </Button>
      </div>

      {loading ? (
        <div className="flex items-center gap-2 text-sm text-gray-400">
          <Loader2 size={14} className="animate-spin" /> Checking service health…
        </div>
      ) : error && !health && !readiness ? (
        <div className="rounded-lg border border-red-500/20 bg-red-500/5 p-4 text-sm text-red-400">
          {error}
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2">
          {services.map((svc) => {
            const ok = svc.status === "ok" || svc.status === "healthy";
            const unknown = svc.status === undefined;

            return (
              <div
                key={svc.name}
                className="flex items-center justify-between rounded-lg border border-[#2a2d37] bg-[#1a1d27] p-4"
              >
                <div className="flex items-center gap-3">
                  <svc.icon size={16} className="text-purple-400" />
                  <span className="text-sm font-medium">{svc.name}</span>
                </div>
                {unknown ? (
                  <StatusBadge ok={false} label="unknown" />
                ) : (
                  <StatusBadge ok={ok} label={svc.status!} />
                )}
              </div>
            );
          })}
        </div>
      )}

      {readiness?.timestamp && (
        <p className="text-xs text-gray-500">
          Last checked: {new Date(readiness.timestamp).toLocaleString()}
        </p>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Tab: Notifications                                                */
/* ------------------------------------------------------------------ */

function NotificationsTab() {
  return (
    <Card icon={Bell} title="Notification Settings">
      <p className="text-sm text-gray-400">
        Configure email, Slack, and webhook notifications for platform events.
      </p>
      <p className="mt-3 text-xs text-gray-500">Coming soon.</p>
    </Card>
  );
}

/* ------------------------------------------------------------------ */
/*  Tab: Appearance                                                   */
/* ------------------------------------------------------------------ */

function AppearanceTab() {
  const [theme, setTheme] = useState<"dark" | "light">("dark");

  return (
    <Card icon={Palette} title="Appearance">
      <p className="mb-4 text-sm text-gray-400">Choose your preferred theme.</p>
      <div className="flex gap-3">
        <Button
          variant={theme === "dark" ? "default" : "outline"}
          size="sm"
          onClick={() => setTheme("dark")}
        >
          <Moon size={14} className="mr-1.5" />
          Dark
        </Button>
        <Button
          variant={theme === "light" ? "default" : "outline"}
          size="sm"
          onClick={() => setTheme("light")}
        >
          <Sun size={14} className="mr-1.5" />
          Light
        </Button>
      </div>
    </Card>
  );
}

/* ------------------------------------------------------------------ */
/*  Page                                                              */
/* ------------------------------------------------------------------ */

export function SettingsPage() {
  const [activeTab, setActiveTab] = useState("general");

  return (
    <div className="p-6">
      <div className="mb-4 flex items-center gap-3">
        <Settings size={24} className="text-purple-400" />
        <h1 className="text-2xl font-bold">Settings</h1>
      </div>
      <p className="mb-6 text-gray-400">
        Platform configuration, system health, and preferences.
      </p>

      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList>
          <TabsTrigger value="general">
            <Info size={14} className="mr-1.5" />
            General
          </TabsTrigger>
          <TabsTrigger value="auth">
            <ShieldCheck size={14} className="mr-1.5" />
            Authentication
          </TabsTrigger>
          <TabsTrigger value="health">
            <Server size={14} className="mr-1.5" />
            System Health
          </TabsTrigger>
          <TabsTrigger value="notifications">
            <Bell size={14} className="mr-1.5" />
            Notifications
          </TabsTrigger>
          <TabsTrigger value="appearance">
            <Palette size={14} className="mr-1.5" />
            Appearance
          </TabsTrigger>
        </TabsList>

        <TabsContent value="general">
          <GeneralTab />
        </TabsContent>
        <TabsContent value="auth">
          <AuthenticationTab />
        </TabsContent>
        <TabsContent value="health">
          <SystemHealthTab />
        </TabsContent>
        <TabsContent value="notifications">
          <NotificationsTab />
        </TabsContent>
        <TabsContent value="appearance">
          <AppearanceTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}
