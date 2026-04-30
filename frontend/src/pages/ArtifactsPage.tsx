/**
 * ArtifactsPage — top-level page that hosts the artifact browser.
 *
 * Wraps ``ArtifactBrowser`` with a page header. Admin detection is via
 * the auth context; the tenant filter is shown only when the user has
 * the ``admin`` role. Non-admins still see filters for run + content
 * type, plus implicit tenant scoping enforced by the backend.
 */

import { Package } from "lucide-react";
import { useAuth } from "@/providers/auth-provider";
import { ArtifactBrowser } from "@/components/artifacts/ArtifactBrowser";

export function ArtifactsPage() {
  const { user } = useAuth();
  const isAdmin = Boolean(
    user && Array.isArray(user.roles) && user.roles.includes("admin"),
  );

  return (
    <div className="p-6">
      <div className="mb-6 flex items-center gap-3">
        <Package size={24} className="text-purple-400" />
        <div>
          <h1 className="text-2xl font-bold text-white">Artifacts</h1>
          <p className="text-sm text-gray-400">
            Inspect, download, and manage large step outputs and run
            artifacts. Cross-tenant artifacts return "not found" by design.
          </p>
        </div>
      </div>
      <ArtifactBrowser showTenantFilter={isAdmin} canDelete />
    </div>
  );
}
