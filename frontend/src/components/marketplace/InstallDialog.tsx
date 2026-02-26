import { Download, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/Button";

interface InstallDialogProps {
  /** Name of the package being installed */
  name: string;
  /** Called when user confirms installation */
  onConfirm: () => void;
  /** Called when user cancels */
  onCancel: () => void;
  /** Whether install is in progress */
  installing: boolean;
}

/**
 * Confirmation dialog shown before installing a marketplace package.
 * Creates an agent from the package template on confirm.
 */
export function InstallDialog({
  name,
  onConfirm,
  onCancel,
  installing,
}: InstallDialogProps) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-label="Install confirmation"
    >
      <div className="w-full max-w-sm rounded-xl border border-surface-border bg-surface-overlay p-6 shadow-2xl">
        <h3 className="mb-2 text-lg font-semibold text-white">
          Install Agent
        </h3>
        <p className="mb-5 text-sm text-gray-400">
          Install{" "}
          <span className="font-medium text-white">{name}</span>? This
          will create a new agent from the package template in your
          workspace.
        </p>
        <div className="flex items-center justify-end gap-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={onCancel}
            disabled={installing}
          >
            Cancel
          </Button>
          <Button
            size="sm"
            className="bg-purple-600 hover:bg-purple-700"
            onClick={onConfirm}
            disabled={installing}
          >
            {installing ? (
              <Loader2 size={14} className="mr-1.5 animate-spin" />
            ) : (
              <Download size={14} className="mr-1.5" />
            )}
            Install
          </Button>
        </div>
      </div>
    </div>
  );
}
