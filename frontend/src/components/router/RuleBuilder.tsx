import { useState, useCallback } from "react";
import { Plus, X, GripVertical } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import type { VisualRoutingRule, RoutingCondition } from "@/api/router";

/* ─── Constants ──────────────────────────────────────────────────── */

const CONDITION_FIELDS = [
  { value: "capability", label: "Capability" },
  { value: "max_cost", label: "Max Cost" },
  { value: "min_context", label: "Min Context" },
  { value: "sensitivity_level", label: "Sensitivity Level" },
  { value: "tenant_tier", label: "Tenant Tier" },
  { value: "time_of_day", label: "Time of Day" },
  { value: "model_preference", label: "Model Preference" },
];

const OPERATORS = [
  { value: "equals", label: "equals" },
  { value: "not_equals", label: "not equals" },
  { value: "contains", label: "contains" },
  { value: "greater_than", label: "greater than" },
  { value: "less_than", label: "less than" },
  { value: "in", label: "in" },
  { value: "not_in", label: "not in" },
];

/* ─── Types ──────────────────────────────────────────────────────── */

interface ModelOption {
  id: string;
  name: string;
}

interface RuleBuilderProps {
  rules: VisualRoutingRule[];
  models: ModelOption[];
  onRulesChange: (rules: VisualRoutingRule[]) => void;
}

/* ─── Component ──────────────────────────────────────────────────── */

export default function RuleBuilder({
  rules,
  models,
  onRulesChange,
}: RuleBuilderProps): JSX.Element {
  const [dragIndex, setDragIndex] = useState<number | null>(null);

  const addRule = useCallback(() => {
    const newRule: VisualRoutingRule = {
      id: null,
      name: `Rule #${rules.length + 1}`,
      description: null,
      conditions: [{ field: "capability", operator: "equals", value: "chat" }],
      target_model_id: models[0]?.id ?? "",
      priority: rules.length,
      enabled: true,
    };
    onRulesChange([...rules, newRule]);
  }, [rules, models, onRulesChange]);

  const removeRule = useCallback(
    (index: number) => {
      const next = rules.filter((_, i) => i !== index);
      onRulesChange(next.map((r, i) => ({ ...r, priority: i })));
    },
    [rules, onRulesChange],
  );

  const toggleRule = useCallback(
    (index: number) => {
      const next = [...rules];
      next[index] = { ...next[index], enabled: !next[index].enabled };
      onRulesChange(next);
    },
    [rules, onRulesChange],
  );

  const updateRuleName = useCallback(
    (index: number, name: string) => {
      const next = [...rules];
      next[index] = { ...next[index], name };
      onRulesChange(next);
    },
    [rules, onRulesChange],
  );

  const updateTargetModel = useCallback(
    (index: number, targetModelId: string) => {
      const next = [...rules];
      next[index] = { ...next[index], target_model_id: targetModelId };
      onRulesChange(next);
    },
    [rules, onRulesChange],
  );

  const addCondition = useCallback(
    (ruleIndex: number) => {
      const next = [...rules];
      const newCond: RoutingCondition = {
        field: "capability",
        operator: "equals",
        value: "",
      };
      next[ruleIndex] = {
        ...next[ruleIndex],
        conditions: [...next[ruleIndex].conditions, newCond],
      };
      onRulesChange(next);
    },
    [rules, onRulesChange],
  );

  const removeCondition = useCallback(
    (ruleIndex: number, condIndex: number) => {
      const next = [...rules];
      next[ruleIndex] = {
        ...next[ruleIndex],
        conditions: next[ruleIndex].conditions.filter((_, i) => i !== condIndex),
      };
      onRulesChange(next);
    },
    [rules, onRulesChange],
  );

  const updateCondition = useCallback(
    (ruleIndex: number, condIndex: number, field: keyof RoutingCondition, val: string) => {
      const next = [...rules];
      const conditions = [...next[ruleIndex].conditions];
      conditions[condIndex] = { ...conditions[condIndex], [field]: val };
      next[ruleIndex] = { ...next[ruleIndex], conditions };
      onRulesChange(next);
    },
    [rules, onRulesChange],
  );

  const handleDragStart = useCallback((index: number) => {
    setDragIndex(index);
  }, []);

  const handleDragOver = useCallback((e: React.DragEvent, index: number) => {
    e.preventDefault();
    if (dragIndex === null || dragIndex === index) return;
    const next = [...rules];
    const [moved] = next.splice(dragIndex, 1);
    next.splice(index, 0, moved);
    onRulesChange(next.map((r, i) => ({ ...r, priority: i })));
    setDragIndex(index);
  }, [dragIndex, rules, onRulesChange]);

  const handleDragEnd = useCallback(() => {
    setDragIndex(null);
  }, []);

  return (
    <div
      className="space-y-3"
      role="region"
      aria-label="Routing rule builder"
    >
      {rules.map((rule, ruleIdx) => (
        <div
          key={rule.id ?? `rule-${ruleIdx}`}
          className={`rounded-lg border p-4 transition-all ${
            rule.enabled
              ? "bg-card dark:bg-card"
              : "bg-muted/50 dark:bg-muted/30 opacity-60"
          } ${dragIndex === ruleIdx ? "ring-2 ring-primary" : ""}`}
          draggable
          onDragStart={() => handleDragStart(ruleIdx)}
          onDragOver={(e) => handleDragOver(e, ruleIdx)}
          onDragEnd={handleDragEnd}
          role="article"
          aria-label={`Routing rule: ${rule.name}`}
        >
          {/* Rule header */}
          <div className="flex items-center gap-2 mb-3">
            <button
              className="cursor-grab active:cursor-grabbing text-muted-foreground hover:text-foreground"
              aria-label="Drag to reorder"
              tabIndex={0}
            >
              <GripVertical className="h-4 w-4" aria-hidden="true" />
            </button>

            <Input
              value={rule.name}
              onChange={(e) => updateRuleName(ruleIdx, e.target.value)}
              className="h-7 text-sm font-medium flex-1 bg-transparent border-none px-1"
              aria-label="Rule name"
            />

            <span className="text-xs text-muted-foreground whitespace-nowrap">
              priority: {rule.priority}
            </span>

            <label className="flex items-center gap-1 text-xs cursor-pointer">
              <input
                type="checkbox"
                checked={rule.enabled}
                onChange={() => toggleRule(ruleIdx)}
                className="rounded"
                aria-label={`${rule.enabled ? "Disable" : "Enable"} rule`}
              />
              <span className="text-muted-foreground">Enabled</span>
            </label>

            <Button
              variant="ghost"
              size="sm"
              onClick={() => removeRule(ruleIdx)}
              className="h-6 w-6 p-0 text-destructive hover:text-destructive"
              aria-label="Delete rule"
            >
              <X className="h-3.5 w-3.5" />
            </Button>
          </div>

          {/* Conditions */}
          <div className="space-y-2 ml-6">
            {rule.conditions.map((cond, condIdx) => (
              <div
                key={condIdx}
                className="flex items-center gap-2 text-sm"
              >
                <span className="text-muted-foreground text-xs w-8">
                  {condIdx === 0 ? "IF" : "AND"}
                </span>

                <select
                  value={cond.field}
                  onChange={(e) => updateCondition(ruleIdx, condIdx, "field", e.target.value)}
                  className="h-8 rounded-md border bg-background dark:bg-muted/30 px-2 text-sm"
                  aria-label="Condition field"
                >
                  {CONDITION_FIELDS.map((f) => (
                    <option key={f.value} value={f.value}>
                      {f.label}
                    </option>
                  ))}
                </select>

                <select
                  value={cond.operator}
                  onChange={(e) => updateCondition(ruleIdx, condIdx, "operator", e.target.value)}
                  className="h-8 rounded-md border bg-background dark:bg-muted/30 px-2 text-sm"
                  aria-label="Condition operator"
                >
                  {OPERATORS.map((op) => (
                    <option key={op.value} value={op.value}>
                      {op.label}
                    </option>
                  ))}
                </select>

                <Input
                  value={String(cond.value)}
                  onChange={(e) => updateCondition(ruleIdx, condIdx, "value", e.target.value)}
                  className="h-8 w-32 text-sm bg-background dark:bg-muted/30"
                  placeholder="value"
                  aria-label="Condition value"
                />

                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => removeCondition(ruleIdx, condIdx)}
                  className="h-6 w-6 p-0 text-muted-foreground hover:text-destructive"
                  aria-label="Remove condition"
                  disabled={rule.conditions.length <= 1}
                >
                  <X className="h-3 w-3" />
                </Button>
              </div>
            ))}

            <Button
              variant="ghost"
              size="sm"
              onClick={() => addCondition(ruleIdx)}
              className="text-xs h-7"
              aria-label="Add condition"
            >
              <Plus className="h-3 w-3 mr-1" />
              Add Condition
            </Button>
          </div>

          {/* Target model */}
          <div className="flex items-center gap-2 mt-3 ml-6 text-sm">
            <span className="text-muted-foreground text-xs">THEN route to →</span>
            <select
              value={rule.target_model_id}
              onChange={(e) => updateTargetModel(ruleIdx, e.target.value)}
              className="h-8 rounded-md border bg-background dark:bg-muted/30 px-2 text-sm flex-1"
              aria-label="Target model"
            >
              <option value="">Select model…</option>
              {models.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name}
                </option>
              ))}
            </select>
          </div>
        </div>
      ))}

      <Button
        variant="outline"
        size="sm"
        onClick={addRule}
        className="w-full gap-1"
        aria-label="Add routing rule"
      >
        <Plus className="h-4 w-4" />
        Add Rule
      </Button>
    </div>
  );
}
