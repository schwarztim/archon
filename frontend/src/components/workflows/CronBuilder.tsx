import { useState, useMemo } from "react";
import { Clock, Globe } from "lucide-react";

// ─── Constants ───────────────────────────────────────────────────────

const SCHEDULE_PRESETS = [
  { label: "Hourly", cron: "0 * * * *" },
  { label: "Daily", cron: "0 9 * * *" },
  { label: "Weekly", cron: "0 9 * * 1" },
  { label: "Monthly", cron: "0 9 1 * *" },
] as const;

const DAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"] as const;
const CRON_DAY_MAP = [1, 2, 3, 4, 5, 6, 0]; // Mon=1 ... Sun=0

const TIMEZONES = [
  "UTC", "America/New_York", "America/Chicago", "America/Denver",
  "America/Los_Angeles", "Europe/London", "Europe/Berlin", "Europe/Paris",
  "Asia/Tokyo", "Asia/Shanghai", "Asia/Kolkata", "Australia/Sydney",
] as const;

// ─── Helpers ─────────────────────────────────────────────────────────

function cronToHuman(cron: string): string {
  if (!cron) return "";
  const parts = cron.split(" ");
  if (parts.length !== 5) return `Cron: ${cron}`;
  const [minute, hour, dayMonth, , dayWeek] = parts;

  const h = hour === "*" ? null : parseInt(hour ?? "0");
  const m = minute === "*" ? 0 : parseInt(minute ?? "0");
  const timeStr = h !== null
    ? `${h.toString().padStart(2, "0")}:${m.toString().padStart(2, "0")}`
    : "every minute";

  if (dayMonth !== "*" && dayMonth !== undefined) {
    return `Monthly on day ${dayMonth} at ${timeStr}`;
  }
  if (dayWeek !== "*" && dayWeek !== undefined) {
    const dayNames = dayWeek.split(",").map((d) => {
      const idx = CRON_DAY_MAP.indexOf(parseInt(d));
      return idx >= 0 ? DAY_LABELS[idx] : d;
    });
    return `Weekly on ${dayNames.join(", ")} at ${timeStr}`;
  }
  if (hour === "*") return `Every hour at minute ${m}`;
  return `Daily at ${timeStr}`;
}

function computeNextRuns(cron: string, count: number = 5): string[] {
  if (!cron) return [];
  const parts = cron.split(" ");
  if (parts.length !== 5) return [];
  const [minStr, hourStr] = parts;
  const targetMin = minStr === "*" ? 0 : parseInt(minStr ?? "0");
  const targetHour = hourStr === "*" ? null : parseInt(hourStr ?? "0");

  const results: string[] = [];
  const now = new Date();
  const candidate = new Date(now);
  candidate.setSeconds(0, 0);

  for (let i = 0; i < count * 400 && results.length < count; i++) {
    candidate.setMinutes(targetMin);
    if (targetHour !== null) candidate.setHours(targetHour);

    if (candidate > now) {
      results.push(
        candidate.toLocaleDateString("en-US", {
          weekday: "short", month: "short", day: "numeric", year: "numeric",
        }) + " at " + candidate.toLocaleTimeString("en-US", {
          hour: "numeric", minute: "2-digit",
        }),
      );
    }

    if (targetHour !== null) {
      candidate.setDate(candidate.getDate() + 1);
    } else {
      candidate.setHours(candidate.getHours() + 1);
    }
  }
  return results;
}

// ─── Component ───────────────────────────────────────────────────────

interface CronBuilderProps {
  value: string;
  onChange: (cron: string) => void;
  timezone?: string;
  onTimezoneChange?: (tz: string) => void;
}

export function CronBuilder({ value, onChange, timezone = "UTC", onTimezoneChange }: CronBuilderProps) {
  const [mode, setMode] = useState<"preset" | "custom">(
    value && !SCHEDULE_PRESETS.some((p) => p.cron === value) ? "custom" : "preset",
  );
  const [selectedDays, setSelectedDays] = useState<number[]>(() => {
    if (!value) return [];
    const parts = value.split(" ");
    if (parts.length === 5 && parts[4] !== "*") {
      return parts[4]?.split(",").map(Number) ?? [];
    }
    return [];
  });
  const [hour, setHour] = useState<string>(() => {
    if (!value) return "09";
    const parts = value.split(" ");
    return parts.length >= 2 && parts[1] !== "*" ? parts[1]?.padStart(2, "0") ?? "09" : "09";
  });
  const [minute, setMinute] = useState<string>(() => {
    if (!value) return "00";
    const parts = value.split(" ");
    return parts.length >= 1 && parts[0] !== "*" ? parts[0]?.padStart(2, "0") ?? "00" : "00";
  });
  const [customMonth, setCustomMonth] = useState("*");
  const [customDom, setCustomDom] = useState("*");

  const humanReadable = useMemo(() => cronToHuman(value), [value]);
  const nextRuns = useMemo(() => computeNextRuns(value, 5), [value]);

  function buildCustomCron(days: number[], h: string, m: string) {
    const dayStr = days.length > 0 ? days.sort().join(",") : "*";
    onChange(`${parseInt(m)} ${parseInt(h)} ${customDom} ${customMonth} ${dayStr}`);
  }

  return (
    <div>
      <label className="mb-1 flex items-center gap-1.5 text-xs text-gray-400">
        <Clock size={12} />
        Schedule
      </label>

      {/* Preset buttons */}
      <div className="mb-2 flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => { onChange(""); setMode("preset"); }}
          className={`rounded px-2.5 py-1 text-xs ${!value ? "bg-purple-500/20 text-purple-300" : "bg-[#12141e] text-gray-500 hover:bg-white/5"}`}
        >
          Manual
        </button>
        {SCHEDULE_PRESETS.map((p) => (
          <button
            key={p.label}
            type="button"
            onClick={() => { onChange(p.cron); setMode("preset"); }}
            className={`rounded px-2.5 py-1 text-xs ${value === p.cron ? "bg-purple-500/20 text-purple-300" : "bg-[#12141e] text-gray-500 hover:bg-white/5"}`}
          >
            {p.label}
          </button>
        ))}
        <button
          type="button"
          onClick={() => setMode("custom")}
          className={`rounded px-2.5 py-1 text-xs ${mode === "custom" && value && !SCHEDULE_PRESETS.some((p) => p.cron === value) ? "bg-purple-500/20 text-purple-300" : "bg-[#12141e] text-gray-500 hover:bg-white/5"}`}
        >
          Custom
        </button>
      </div>

      {/* Custom schedule builder */}
      {mode === "custom" && (
        <div className="rounded-lg border border-[#2a2d37] bg-[#12141e] p-3 space-y-3">
          {/* Days of week */}
          <div>
            <label className="mb-0.5 block text-[10px] text-gray-500">Days of week</label>
            <div className="flex gap-1">
              {DAY_LABELS.map((d, i) => {
                const cronDay = CRON_DAY_MAP[i]!;
                const active = selectedDays.includes(cronDay);
                return (
                  <button
                    key={d}
                    type="button"
                    onClick={() => {
                      const next = active ? selectedDays.filter((x) => x !== cronDay) : [...selectedDays, cronDay];
                      setSelectedDays(next);
                      buildCustomCron(next, hour ?? "09", minute ?? "00");
                    }}
                    className={`rounded px-2 py-0.5 text-[10px] ${active ? "bg-purple-500/20 text-purple-300" : "bg-[#1a1d27] text-gray-500 hover:bg-white/5"}`}
                  >
                    {d}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Time: minute, hour */}
          <div className="flex gap-2 items-end">
            <div>
              <label className="mb-0.5 block text-[10px] text-gray-500">Hour</label>
              <select
                value={hour}
                onChange={(e) => { setHour(e.target.value); buildCustomCron(selectedDays, e.target.value, minute); }}
                className="w-20 rounded border border-[#2a2d37] bg-[#1a1d27] px-2 py-1 text-xs text-white focus:border-purple-500 focus:outline-none"
              >
                {Array.from({ length: 24 }, (_, i) => (
                  <option key={i} value={i.toString().padStart(2, "0")}>{i.toString().padStart(2, "0")}</option>
                ))}
              </select>
            </div>
            <span className="text-gray-500 pb-1">:</span>
            <div>
              <label className="mb-0.5 block text-[10px] text-gray-500">Minute</label>
              <select
                value={minute}
                onChange={(e) => { setMinute(e.target.value); buildCustomCron(selectedDays, hour, e.target.value); }}
                className="w-20 rounded border border-[#2a2d37] bg-[#1a1d27] px-2 py-1 text-xs text-white focus:border-purple-500 focus:outline-none"
              >
                {[0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55].map((m) => (
                  <option key={m} value={m.toString().padStart(2, "0")}>{m.toString().padStart(2, "0")}</option>
                ))}
              </select>
            </div>

            {/* Day of month */}
            <div>
              <label className="mb-0.5 block text-[10px] text-gray-500">Day of month</label>
              <select
                value={customDom}
                onChange={(e) => { setCustomDom(e.target.value); buildCustomCron(selectedDays, hour, minute); }}
                className="w-20 rounded border border-[#2a2d37] bg-[#1a1d27] px-2 py-1 text-xs text-white focus:border-purple-500 focus:outline-none"
              >
                <option value="*">Any</option>
                {Array.from({ length: 31 }, (_, i) => (
                  <option key={i + 1} value={(i + 1).toString()}>{i + 1}</option>
                ))}
              </select>
            </div>

            {/* Month */}
            <div>
              <label className="mb-0.5 block text-[10px] text-gray-500">Month</label>
              <select
                value={customMonth}
                onChange={(e) => { setCustomMonth(e.target.value); buildCustomCron(selectedDays, hour, minute); }}
                className="w-20 rounded border border-[#2a2d37] bg-[#1a1d27] px-2 py-1 text-xs text-white focus:border-purple-500 focus:outline-none"
              >
                <option value="*">Any</option>
                {["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"].map((m, i) => (
                  <option key={m} value={(i + 1).toString()}>{m}</option>
                ))}
              </select>
            </div>
          </div>
        </div>
      )}

      {/* Timezone selector */}
      {onTimezoneChange && (
        <div className="mt-2 flex items-center gap-2">
          <Globe size={10} className="text-gray-500" />
          <select
            value={timezone}
            onChange={(e) => onTimezoneChange(e.target.value)}
            className="rounded border border-[#2a2d37] bg-[#12141e] px-2 py-0.5 text-[10px] text-gray-400 focus:border-purple-500 focus:outline-none"
          >
            {TIMEZONES.map((tz) => (
              <option key={tz} value={tz}>{tz}</option>
            ))}
          </select>
        </div>
      )}

      {/* Human-readable + next runs */}
      {value && (
        <div className="mt-2 space-y-1 rounded-lg border border-[#2a2d37] bg-[#12141e] p-2">
          <p className="text-[10px] font-medium text-gray-400">{humanReadable}</p>
          {nextRuns.length > 0 && (
            <div>
              <p className="text-[9px] text-gray-600 mb-0.5">Next {nextRuns.length} runs:</p>
              {nextRuns.map((r, i) => (
                <p key={i} className="text-[9px] text-purple-400">• {r}</p>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
