import { useState, useEffect, useCallback } from "react";
import { Eye, EyeOff, CheckCircle2, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import {
  getCredentialSchemas,
  saveProviderCredentials,
  type CredentialField,
  type ProviderCredentialSchema,
} from "@/api/router";

/* ─── Types ──────────────────────────────────────────────────────── */

interface ProviderFormProps {
  providerId: string;
  providerType: string;
  hasCredentialsSaved: boolean;
  onCredentialsSaved: () => void;
}

/* ─── Component ──────────────────────────────────────────────────── */

export default function ProviderForm({
  providerId,
  providerType,
  hasCredentialsSaved,
  onCredentialsSaved,
}: ProviderFormProps): JSX.Element {
  const [schemas, setSchemas] = useState<Record<string, ProviderCredentialSchema>>({});
  const [values, setValues] = useState<Record<string, string>>({});
  const [revealedFields, setRevealedFields] = useState<Set<string>>(new Set());
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(hasCredentialsSaved);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getCredentialSchemas()
      .then((res) => setSchemas(res.data))
      .catch(() => setSchemas({}));
  }, []);

  useEffect(() => {
    setSaved(hasCredentialsSaved);
  }, [hasCredentialsSaved]);

  const schema = schemas[providerType];

  const handleFieldChange = useCallback(
    (fieldName: string, val: string) => {
      setValues((prev) => ({ ...prev, [fieldName]: val }));
      setSaved(false);
    },
    [],
  );

  const toggleReveal = useCallback((fieldName: string) => {
    setRevealedFields((prev) => {
      const next = new Set(prev);
      if (next.has(fieldName)) {
        next.delete(fieldName);
      } else {
        next.add(fieldName);
      }
      return next;
    });
  }, []);

  const handleSave = useCallback(async () => {
    const nonEmpty = Object.fromEntries(
      Object.entries(values).filter(([, v]) => v.trim() !== ""),
    );
    if (Object.keys(nonEmpty).length === 0) {
      setError("Please fill in at least one credential field.");
      return;
    }

    setSaving(true);
    setError(null);
    try {
      await saveProviderCredentials(providerId, nonEmpty);
      setSaved(true);
      onCredentialsSaved();
    } catch {
      setError("Failed to save credentials. Please try again.");
    } finally {
      setSaving(false);
    }
  }, [values, providerId, onCredentialsSaved]);

  if (!schema) {
    return (
      <div className="text-sm text-muted-foreground" role="status">
        No credential schema available for provider type &quot;{providerType}&quot;.
      </div>
    );
  }

  return (
    <div className="space-y-4" role="form" aria-label="Provider credentials form">
      <h4 className="text-sm font-medium text-foreground">
        {schema.label} Credentials
      </h4>

      {schema.fields.map((field: CredentialField) => {
        const isPassword = field.field_type === "password";
        const isRevealed = revealedFields.has(field.name);

        return (
          <div key={field.name} className="space-y-1">
            <Label htmlFor={`cred-${field.name}`} className="text-sm">
              {field.label}
              {field.required && (
                <span className="text-destructive ml-1" aria-label="required">*</span>
              )}
            </Label>
            <div className="flex gap-2">
              <Input
                id={`cred-${field.name}`}
                type={isPassword && !isRevealed ? "password" : "text"}
                placeholder={
                  saved && !values[field.name]
                    ? "••••••••"
                    : field.placeholder
                }
                value={values[field.name] ?? ""}
                onChange={(e) => handleFieldChange(field.name, e.target.value)}
                className="flex-1 bg-background dark:bg-muted/30"
                aria-label={field.label}
                aria-required={field.required}
              />
              {isPassword && (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => toggleReveal(field.name)}
                  aria-label={isRevealed ? "Hide credential" : "Show credential"}
                  className="px-2"
                >
                  {isRevealed ? (
                    <EyeOff className="h-4 w-4" />
                  ) : (
                    <Eye className="h-4 w-4" />
                  )}
                </Button>
              )}
            </div>
            {field.description && (
              <p className="text-xs text-muted-foreground">{field.description}</p>
            )}
          </div>
        );
      })}

      {saved && (
        <div
          className="flex items-center gap-1 text-sm text-green-600 dark:text-green-400"
          role="status"
          aria-label="Credentials saved"
        >
          <CheckCircle2 className="h-4 w-4" />
          <span>Key saved ✓</span>
        </div>
      )}

      {error && (
        <div
          className="text-sm text-destructive"
          role="alert"
        >
          {error}
        </div>
      )}

      <Button
        onClick={handleSave}
        disabled={saving}
        size="sm"
        aria-label="Save credentials"
      >
        {saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
        {saving ? "Saving…" : "Save Credentials"}
      </Button>
    </div>
  );
}
