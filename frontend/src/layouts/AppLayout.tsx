import { useCallback, useState } from "react";
import { Outlet } from "react-router-dom";
import { Sidebar, TopBar } from "@/components/navigation";

export function AppLayout() {
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  const toggleSidebar = useCallback(() => setCollapsed((c) => !c), []);
  const toggleMobile = useCallback(() => setMobileOpen((o) => !o), []);
  const closeMobile = useCallback(() => setMobileOpen(false), []);

  return (
    <div className="flex h-screen bg-surface-base text-white dark:bg-surface-base">
      {/* Sidebar */}
      <Sidebar
        collapsed={collapsed}
        onToggle={toggleSidebar}
        mobileOpen={mobileOpen}
        onMobileClose={closeMobile}
      />

      {/* Main area */}
      <div className="flex flex-1 flex-col overflow-hidden">
        {/* Top bar */}
        <TopBar onMenuToggle={toggleMobile} />

        {/* Page content */}
        <main className="flex-1 overflow-auto">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
