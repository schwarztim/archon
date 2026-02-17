import { Wallet, Plus, X } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { BudgetBar } from "./BudgetBar";

interface BudgetItem {
  id: string;
  name: string;
  scope: string;
  limit_amount: number;
  spent_amount: number;
  period: string;
  enforcement: string;
  alert_thresholds?: number[];
  utilization_pct?: number;
  utilization_color?: string;
}

interface BudgetListProps {
  budgets: BudgetItem[];
  showWizard: boolean;
  onToggleWizard: () => void;
  children?: React.ReactNode;
}

export function BudgetList({ budgets, showWizard, onToggleWizard, children }: BudgetListProps) {
  return (
    <div className="mb-6 rounded-lg border border-[#2a2d37] bg-[#1a1d27]">
      <div className="flex items-center justify-between border-b border-[#2a2d37] px-4 py-3">
        <h2 className="text-sm font-semibold text-white">Budgets</h2>
        <Button size="sm" className="bg-purple-600 hover:bg-purple-700" onClick={onToggleWizard}>
          {showWizard ? (
            <><X size={14} className="mr-1.5" /> Cancel</>
          ) : (
            <><Plus size={14} className="mr-1.5" /> Create Budget</>
          )}
        </Button>
      </div>

      {showWizard && children}

      <div className="divide-y divide-[#2a2d37]">
        {budgets.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12">
            <Wallet size={32} className="mb-2 text-gray-600" />
            <p className="text-sm text-gray-500">No budgets configured yet.</p>
          </div>
        ) : (
          budgets.map((b) => (
            <BudgetBar
              key={b.id}
              name={b.name}
              spent={b.spent_amount ?? 0}
              limit={b.limit_amount}
              enforcement={b.enforcement}
              scope={b.scope}
              period={b.period}
              thresholds={b.alert_thresholds}
            />
          ))
        )}
      </div>
    </div>
  );
}
