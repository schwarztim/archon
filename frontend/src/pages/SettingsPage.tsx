import { useState } from "react";
import {
  Settings,
  Info,
  ShieldCheck,
  Bell,
  Palette,
  Server,
  Key,
  ToggleLeft,
} from "lucide-react";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { GeneralTab } from "@/components/settings/GeneralTab";
import { AuthTab } from "@/components/settings/AuthTab";
import { APITab } from "@/components/settings/APITab";
import { NotificationsTab } from "@/components/settings/NotificationsTab";
import { FeatureFlagsTab } from "@/components/settings/FeatureFlagsTab";
import { SystemHealthTab } from "@/components/settings/SystemHealthTab";
import { AppearanceTab } from "@/components/settings/AppearanceTab";

/* ------------------------------------------------------------------ */
/*  Page                                                              */
/* ------------------------------------------------------------------ */

/** Check if the current user has admin role (reads from localStorage/session). */
function useIsAdmin(): boolean {
  try {
    const raw = localStorage.getItem("archon-session");
    if (raw) {
      const session = JSON.parse(raw);
      const roles: string[] = session?.user?.roles ?? [];
      return roles.includes("admin");
    }
  } catch {
    // fall through
  }
  // Default to true in dev to allow access
  return true;
}

export function SettingsPage() {
  const [activeTab, setActiveTab] = useState("general");
  const isAdmin = useIsAdmin();

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
          <TabsTrigger value="api">
            <Key size={14} className="mr-1.5" />
            API &amp; Integrations
          </TabsTrigger>
          <TabsTrigger value="notifications">
            <Bell size={14} className="mr-1.5" />
            Notifications
          </TabsTrigger>
          {isAdmin && (
            <TabsTrigger value="feature-flags">
              <ToggleLeft size={14} className="mr-1.5" />
              Feature Flags
            </TabsTrigger>
          )}
          {isAdmin && (
            <TabsTrigger value="health">
              <Server size={14} className="mr-1.5" />
              System Health
            </TabsTrigger>
          )}
          <TabsTrigger value="appearance">
            <Palette size={14} className="mr-1.5" />
            Appearance
          </TabsTrigger>
        </TabsList>

        <TabsContent value="general">
          <GeneralTab />
        </TabsContent>
        <TabsContent value="auth">
          <AuthTab />
        </TabsContent>
        <TabsContent value="api">
          <APITab />
        </TabsContent>
        <TabsContent value="notifications">
          <NotificationsTab />
        </TabsContent>
        {isAdmin && (
          <TabsContent value="feature-flags">
            <FeatureFlagsTab />
          </TabsContent>
        )}
        {isAdmin && (
          <TabsContent value="health">
            <SystemHealthTab />
          </TabsContent>
        )}
        <TabsContent value="appearance">
          <AppearanceTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}
