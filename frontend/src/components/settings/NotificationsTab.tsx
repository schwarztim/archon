import { useState } from "react";
import { Bell, Mail, MessageSquare } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { useTestNotification } from "@/hooks/useSettings";

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
    <div className="rounded-lg border border-surface-border bg-surface-raised p-5">
      <h2 className="mb-4 flex items-center gap-2 text-sm font-semibold">
        <Icon size={14} className="text-purple-400" />
        {title}
      </h2>
      {children}
    </div>
  );
}

export function NotificationsTab() {
  const [smtpHost, setSmtpHost] = useState("");
  const [smtpPort, setSmtpPort] = useState("587");
  const [smtpFrom, setSmtpFrom] = useState("");
  const [smtpUser, setSmtpUser] = useState("");
  const [smtpPass, setSmtpPass] = useState("");
  const [slackWebhook, setSlackWebhook] = useState("");
  const [events, setEvents] = useState({
    agent_failure: true,
    deployment: true,
    security_alert: true,
  });

  const testNotification = useTestNotification();

  const handleTestEmail = () => {
    testNotification.mutate({ channel: "email", recipient: smtpFrom });
  };

  const handleTestSlack = () => {
    testNotification.mutate({ channel: "slack" });
  };

  const testStatus = testNotification.isPending
    ? "sending..."
    : testNotification.isSuccess
      ? testNotification.data?.data?.message ?? "Test sent!"
      : testNotification.isError
        ? "Failed to send"
        : null;

  return (
    <div className="space-y-6">
      <Card icon={Mail} title="SMTP Configuration">
        <p className="mb-4 text-sm text-gray-400">
          Configure email delivery. SMTP password is stored securely in Vault.
        </p>
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor="smtp-host">SMTP Host</Label>
            <Input
              id="smtp-host"
              placeholder="smtp.example.com"
              value={smtpHost}
              onChange={(e) => setSmtpHost(e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="smtp-port">SMTP Port</Label>
            <Input
              id="smtp-port"
              placeholder="587"
              value={smtpPort}
              onChange={(e) => setSmtpPort(e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="smtp-from">From Address</Label>
            <Input
              id="smtp-from"
              placeholder="noreply@archon.io"
              value={smtpFrom}
              onChange={(e) => setSmtpFrom(e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="smtp-user">Username</Label>
            <Input
              id="smtp-user"
              placeholder="apikey"
              value={smtpUser}
              onChange={(e) => setSmtpUser(e.target.value)}
            />
          </div>
          <div className="space-y-1.5 sm:col-span-2">
            <Label htmlFor="smtp-pass">Password (stored in Vault)</Label>
            <Input
              id="smtp-pass"
              type="password"
              placeholder="••••••••"
              value={smtpPass}
              onChange={(e) => setSmtpPass(e.target.value)}
            />
          </div>
        </div>
        <div className="mt-4 flex gap-3">
          <Button variant="secondary" size="sm" onClick={handleTestEmail}>
            Send Test Email
          </Button>
          <Button variant="secondary" size="sm" disabled>
            Save
          </Button>
        </div>
      </Card>

      <Card icon={MessageSquare} title="Slack Integration">
        <div className="space-y-3">
          <div className="space-y-1.5">
            <Label htmlFor="slack-webhook">Slack Webhook URL</Label>
            <Input
              id="slack-webhook"
              placeholder="https://hooks.slack.com/services/..."
              value={slackWebhook}
              onChange={(e) => setSlackWebhook(e.target.value)}
            />
          </div>
          <Button variant="secondary" size="sm" onClick={handleTestSlack}>
            Send Test Message
          </Button>
        </div>
      </Card>

      <Card icon={Bell} title="Event Preferences">
        <div className="space-y-3">
          {[
            { key: "agent_failure" as const, label: "Agent failures" },
            { key: "deployment" as const, label: "Deployment events" },
            { key: "security_alert" as const, label: "Security alerts" },
          ].map((item) => (
            <label key={item.key} className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={events[item.key]}
                onChange={(e) =>
                  setEvents((prev) => ({ ...prev, [item.key]: e.target.checked }))
                }
                className="rounded border-gray-600 accent-purple-500"
              />
              {item.label}
            </label>
          ))}
        </div>
      </Card>

      {testStatus && (
        <p className="text-sm text-gray-400">{testStatus}</p>
      )}
    </div>
  );
}
