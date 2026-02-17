import { useState } from "react";
import { ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";

type SsoProtocol = "oidc" | "saml";

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

export function AuthTab() {
  const [protocol, setProtocol] = useState<SsoProtocol>("oidc");
  const [discoveryUrl, setDiscoveryUrl] = useState("");
  const [clientId, setClientId] = useState("");
  const [redirectUri, setRedirectUri] = useState(
    `${window.location.origin}/callback`,
  );
  const [sessionTimeout, setSessionTimeout] = useState(480);
  const [mfaEnabled, setMfaEnabled] = useState(false);
  const [pwdMinLength, setPwdMinLength] = useState(true);
  const [pwdRequireUpper, setPwdRequireUpper] = useState(true);
  const [pwdRequireNumbers, setPwdRequireNumbers] = useState(true);
  const [pwdRequireSpecial, setPwdRequireSpecial] = useState(true);

  return (
    <div className="space-y-6">
      <Card icon={ShieldCheck} title="SSO Configuration">
        <p className="mb-5 text-sm text-gray-400">
          Configure your OIDC/SAML identity provider.
        </p>
        <div className="space-y-4">
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
          <div className="space-y-1.5">
            <Label htmlFor="sso-discovery">Discovery URL</Label>
            <Input
              id="sso-discovery"
              placeholder="https://idp.example.com/.well-known/openid-configuration"
              value={discoveryUrl}
              onChange={(e) => setDiscoveryUrl(e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="sso-client-id">Client ID</Label>
            <Input
              id="sso-client-id"
              placeholder="archon-platform"
              value={clientId}
              onChange={(e) => setClientId(e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="sso-redirect">Redirect URI</Label>
            <Input
              id="sso-redirect"
              value={redirectUri}
              onChange={(e) => setRedirectUri(e.target.value)}
            />
          </div>
          <div className="flex gap-3 pt-2">
            <Button disabled>Test Connection</Button>
            <Button variant="secondary" disabled>Save</Button>
          </div>
        </div>
      </Card>

      <Card icon={ShieldCheck} title="Session & Security">
        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="session-timeout">
              Session Timeout: {sessionTimeout} minutes
            </Label>
            <input
              id="session-timeout"
              type="range"
              min={15}
              max={1440}
              step={15}
              value={sessionTimeout}
              onChange={(e) => setSessionTimeout(Number(e.target.value))}
              className="w-full accent-purple-500"
              aria-label="Session timeout slider"
            />
            <div className="flex justify-between text-xs text-gray-500">
              <span>15 min</span>
              <span>24 hrs</span>
            </div>
          </div>

          <div className="space-y-3">
            <Label>Password Policy</Label>
            {[
              { label: "Minimum 12 characters", checked: pwdMinLength, set: setPwdMinLength },
              { label: "Require uppercase", checked: pwdRequireUpper, set: setPwdRequireUpper },
              { label: "Require numbers", checked: pwdRequireNumbers, set: setPwdRequireNumbers },
              { label: "Require special characters", checked: pwdRequireSpecial, set: setPwdRequireSpecial },
            ].map((item) => (
              <label key={item.label} className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={item.checked}
                  onChange={(e) => item.set(e.target.checked)}
                  className="rounded border-gray-600 accent-purple-500"
                />
                {item.label}
              </label>
            ))}
          </div>

          <label className="flex items-center gap-2 pt-2 text-sm">
            <input
              type="checkbox"
              checked={mfaEnabled}
              onChange={(e) => setMfaEnabled(e.target.checked)}
              className="rounded border-gray-600 accent-purple-500"
            />
            Require Multi-Factor Authentication (MFA)
          </label>
        </div>
      </Card>
    </div>
  );
}
