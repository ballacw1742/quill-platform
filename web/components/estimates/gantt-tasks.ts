import type { ScheduleActivity, ScheduleBlock } from "@/lib/schemas";

/**
 * Pure helpers for converting a Quill ScheduleBlock into frappe-gantt task
 * objects. Lives outside GanttChart.tsx so tests can import without pulling
 * the CSS / DOM imports a "use client" component carries.
 */

export type GanttTask = {
  id: string;
  name: string;
  start: string; // YYYY-MM-DD
  end: string; // YYYY-MM-DD (inclusive, frappe-gantt convention)
  progress?: number;
  dependencies?: string;
  custom_class?: string;
};

const MS_PER_DAY = 86_400_000;

export function activitiesToGanttTasks(schedule: ScheduleBlock): GanttTask[] {
  const activities = schedule.activities ?? [];
  if (activities.length === 0) return [];

  const byId = new Map<string, ScheduleActivity>();
  for (const a of activities) byId.set(a.id, a);

  const visited = new Set<string>();
  const order: string[] = [];
  const visiting = new Set<string>();
  const visit = (id: string) => {
    if (visited.has(id)) return;
    if (visiting.has(id)) return; // cycle — break
    visiting.add(id);
    const a = byId.get(id);
    if (a) {
      for (const p of a.predecessors ?? []) {
        if (byId.has(p.id)) visit(p.id);
      }
    }
    visiting.delete(id);
    visited.add(id);
    order.push(id);
  };
  for (const a of activities) visit(a.id);

  const start = new Map<string, number>();
  const end = new Map<string, number>();
  const projectStart = startOfTodayUtc();

  for (const id of order) {
    const a = byId.get(id);
    if (!a) continue;
    const dur = Math.max(1, a.duration_days || 1);
    const preds = a.predecessors ?? [];
    let earliestStart = projectStart;
    for (const p of preds) {
      const ps = start.get(p.id);
      const pe = end.get(p.id);
      if (ps == null || pe == null) continue;
      const lag = (p.lag_days ?? 0) * MS_PER_DAY;
      let candidate = earliestStart;
      switch ((p.type || "FS").toUpperCase()) {
        case "SS":
          candidate = ps + lag;
          break;
        case "FF":
          candidate = pe + lag - dur * MS_PER_DAY;
          break;
        case "SF":
          candidate = ps + lag - dur * MS_PER_DAY;
          break;
        default: // FS
          candidate = pe + lag;
      }
      if (candidate > earliestStart) earliestStart = candidate;
    }
    const endTs = earliestStart + dur * MS_PER_DAY;
    start.set(id, earliestStart);
    end.set(id, endTs);
  }

  return activities.map((a) => {
    const s = start.get(a.id) ?? projectStart;
    const e = end.get(a.id) ?? s + Math.max(1, a.duration_days || 1) * MS_PER_DAY;
    const deps = (a.predecessors ?? []).map((p) => p.id).join(",");
    return {
      id: a.id,
      name: a.name || a.id,
      start: toIsoDate(s),
      end: toIsoDate(e - MS_PER_DAY), // inclusive end
      progress: 0,
      dependencies: deps,
      custom_class: a.critical_path
        ? "gantt-critical"
        : a.milestone
          ? "gantt-milestone"
          : "",
    };
  });
}

export function pickViewMode(
  tasks: GanttTask[],
): "Day" | "Week" | "Month" {
  if (tasks.length === 0) return "Day";
  let min = Infinity,
    max = -Infinity;
  for (const t of tasks) {
    const s = Date.parse(t.start);
    const e = Date.parse(t.end);
    if (Number.isFinite(s) && s < min) min = s;
    if (Number.isFinite(e) && e > max) max = e;
  }
  if (!Number.isFinite(min) || !Number.isFinite(max)) return "Day";
  const days = (max - min) / MS_PER_DAY;
  if (days <= 14) return "Day";
  if (days <= 60) return "Week";
  return "Month";
}

function startOfTodayUtc(): number {
  const d = new Date();
  return Date.UTC(d.getFullYear(), d.getMonth(), d.getDate());
}
function toIsoDate(ms: number): string {
  const d = new Date(ms);
  const y = d.getUTCFullYear();
  const m = String(d.getUTCMonth() + 1).padStart(2, "0");
  const day = String(d.getUTCDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}
