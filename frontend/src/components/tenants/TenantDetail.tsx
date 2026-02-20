import { useState, useEffect } from "react";
import { ArrowLeft, Building2, ShieldCheck, BarChart3, Users, CreditCard } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { UsageStats } from "./UsageStats";
import { MemberTable, type TenantMember } from "./MemberTable";
import { IdPList } from "@/components/sso/IdPList";
import { apiGet, apiPost } from "@/api/client";

interface TenantDetailProps {
  tenant: {
    id: string;
    name: string;
    slug: string;
    tier: string;
    status: string;
    owner_email: string;
    created_at: string;
  };
  onBack: () => void;
}

interface IdPConfig {
  id: string;
  name: string;
  protocol: string;
  enabled: boolean;
  is_default: boolean;
  created_at: string;
}

function tierBadge(tier: string) {
  const cls: Record<string, string> = {
    enterprise: "bg-purple-500/20 text-purple-400",
    team: "bg-blue-500/20 text-blue-400",
    individual: "bg-green-500/20 text-green-400",
    free: "bg-gray-500/20 text-gray-400",
  };
  return (
    <span className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium ${cls[tier] ?? "bg-gray-500/20 text-gray-400"}`}>
      {tier}
    </span>
  );
}

function statusBadge(status: string) {
  const cls: Record<string, string> = {
    active: "bg-green-500/20 text-green-400",
    suspended: "bg-red-500/20 text-red-400",
  };
  return (
    <span className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium ${cls[status] ?? "bg-gray-500/20 text-gray-400"}`}>
      {status}
    </span>
  );
}

export function TenantDetail({ tenant, onBack }: TenantDetailProps) {
  const [idpConfigs, setIdpConfigs] = useState<IdPConfig[]>([]);
  const [members, setMembers] = useState<TenantMember[]>([]);
  const [activeTab, setActiveTab] = useState("general");
  const [usageStats, setUsageStats] = useState({
    agents: { current: 0, max: 5 },
    executions: { current: 0, max: 100 },
    storage_mb: { current: 0, max: 100 },
  });

  useEffect(() => {
    void loadData();
  }, [tenant.id]);

  async function loadData() {
    const [idpRes, membersRes, usageRes] = await Promise.allSettled([
      apiGet<IdPConfig[]>(`/tenants/${tenant.id}/sso`),
      apiGet<TenantMember[]>(`/tenants/${tenant.id}/members`),
      apiGet<{ executions: number; tokens: number; storage_mb: number }>(`/tenants/${tenant.id}/usage`),
    ]);
    if (idpRes.status === "fulfilled") {
      setIdpConfigs(Array.isArray(idpRes.value.data) ? idpRes.value.data : []);
    }
    if (membersRes.status === "fulfilled") {
      setMembers(Array.isArray(membersRes.value.data) ? membersRes.value.data : []);
    }
    if (usageRes.status === "fulfilled" && usageRes.value.data) {
      const d = usageRes.value.data;
      setUsageStats({
        agents: { current: 0, max: 5 },
        executions: { current: d.executions ?? 0, max: 100 },
        storage_mb: { current: d.storage_mb ?? 0, max: 100 },
      });
    }
  }

  async function handleImpersonate(userId: string) {
    try {
      await apiPost(`/users/${userId}/impersonate`, { reason: "Admin troubleshooting" });
    } catch {
      // silently fail for demo
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <Button size="sm" variant="ghost" onClick={onBack}>
          <ArrowLeft size={16} />
        </Button>
        <Building2 size={22} className="text-purple-400" />
        <h2 className="text-xl font-bold text-white">{tenant.name}</h2>
        {tierBadge(tenant.tier)}
        {statusBadge(tenant.status)}
      </div>

      <Tabs value={activeTab} onValueChange={setActiveTab} defaultValue="general">
        <TabsList className="bg-[#1a1d27] dark:bg-[#1a1d27]">
          <TabsTrigger value="general">
            <Building2 size={14} className="mr-1.5" />General
          </TabsTrigger>
          <TabsTrigger value="idp">
            <ShieldCheck size={14} className="mr-1.5" />Identity Providers
          </TabsTrigger>
          <TabsTrigger value="usage">
            <BarChart3 size={14} className="mr-1.5" />Usage & Quotas
          </TabsTrigger>
          <TabsTrigger value="members">
            <Users size={14} className="mr-1.5" />Members
          </TabsTrigger>
          <TabsTrigger value="billing">
            <CreditCard size={14} className="mr-1.5" />Billing
          </TabsTrigger>
        </TabsList>

        <TabsContent value="general">
          <div className="rounded-lg border border-[#2a2d37] bg-[#1a1d27] p-6 dark:bg-[#1a1d27]">
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <div className="space-y-3">
                <div>
                  <span className="text-xs text-gray-500">Name</span>
                  <p className="font-medium text-white">{tenant.name}</p>
                </div>
                <div>
                  <span className="text-xs text-gray-500">Slug</span>
                  <p className="font-mono text-white">{tenant.slug}</p>
                </div>
                <div>
                  <span className="text-xs text-gray-500">Owner</span>
                  <p className="text-white">{tenant.owner_email}</p>
                </div>
              </div>
              <div className="space-y-3">
                <div>
                  <span className="text-xs text-gray-500">Tier</span>
                  <p>{tierBadge(tenant.tier)}</p>
                </div>
                <div>
                  <span className="text-xs text-gray-500">Status</span>
                  <p>{statusBadge(tenant.status)}</p>
                </div>
                <div>
                  <span className="text-xs text-gray-500">Created</span>
                  <p className="text-white">{new Date(tenant.created_at).toLocaleDateString()}</p>
                </div>
              </div>
            </div>
          </div>
        </TabsContent>

        <TabsContent value="idp">
          <IdPList
            configs={idpConfigs}
            onEdit={() => {}}
            onDelete={() => {}}
            onTest={() => {}}
            onToggle={() => {}}
            onSetDefault={() => {}}
          />
        </TabsContent>

        <TabsContent value="usage">
          <UsageStats stats={usageStats} />
        </TabsContent>

        <TabsContent value="members">
          <MemberTable members={members} onImpersonate={handleImpersonate} />
        </TabsContent>

        <TabsContent value="billing">
          <div className="rounded-lg border border-[#2a2d37] bg-[#1a1d27] p-6 dark:bg-[#1a1d27]">
            <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
              <div>
                <span className="text-xs text-gray-500">Plan</span>
                <p className="mt-1">{tierBadge(tenant.tier)}</p>
              </div>
              <div>
                <span className="text-xs text-gray-500">Usage This Month</span>
                <p className="text-lg font-semibold text-white">
                  {usageStats.executions.current.toLocaleString()} executions
                </p>
              </div>
              <div>
                <span className="text-xs text-gray-500">Estimated Cost</span>
                <p className="text-lg font-semibold text-white">
                  ${(usageStats.executions.current * 0.01).toFixed(2)}
                </p>
              </div>
            </div>
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
}
