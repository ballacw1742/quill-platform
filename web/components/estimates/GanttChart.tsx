"use client";

import * as React from "react";
import "./frappe-gantt.css";
import type { ScheduleActivity, ScheduleBlock } from "@/lib/schemas";

// frappe-gantt has no type defs shipped; declare a permissive ambient type so
// tsc stays happy. The actual library is loaded dynamically client-side.
type GanttCtor = new (
  el: HTMLElement | SVGElement | string,
  tasks: GanttTask[],
  options?: GanttOptions,
) => unknown;

type GanttTask = {
  id: string;
  name: string;
  start: string;
  end: string;
  progress?: number;
  dependencies?: string;
  custom_class?: string;
};

type GanttOptions = {
  view_mode?: "Quarter Day" | "Half Day" | "Day" | "Week" | "Month";
  bar_height?: number;
  padding?: number;
  language?: string;
  popup_trigger?: "click" | "mouseover";
  custom_popup_html?: ((task: unknown) => string) | null;
};

const MS_PER_DAY = 86_400_000;

/**
 * Convert a CostSchedulePackage schedule into frappe-gantt task list.
 *
 * The schema doesn't store explicit start/end dates per activity (it's a
 * duration + predecessors network), so we derive them by resolving the network
 * topologically. The "project anchor" is "today" — this is a visualisation of
 * the schedule shape, not a baseline.
 *
 * Predecessor types currently honoured: FS (default), SS, FF (best-effort),
 * SF (best-effort). lag_days is added.
 */
export function activitiesToGanttTasks(schedule: ScheduleBlock): GanttTask[] {
  const activities = schedule.activities ?? [];
  if (activities.length === 0) return [];

  const byId = new Map<string, ScheduleActivity>();
  for (const a of activities) byId.set(a.id, a);

  // Topological order
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

  const start = new Map<string, number>(); // ms epoch
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
      end: toIsoDate(e - MS_PER_DAY), // frappe-gantt treats end as inclusive
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

export function GanttChart({ schedule }: { schedule: ScheduleBlock }) {
  const containerRef = React.useRef<HTMLDivElement | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [ready, setReady] = React.useState(false);
  const tasks = React.useMemo(() => activitiesToGanttTasks(schedule), [schedule]);

  React.useEffect(() => {
    let cancelled = false;
    if (!containerRef.current) return;
    const el = containerRef.current;
    el.innerHTML = ""; // wipe prior render
    if (tasks.length === 0) {
      setReady(true);
      return;
    }

    (async () => {
      try {
        // Dynamic import keeps frappe-gantt out of the SSR bundle and avoids
        // 'window is not defined' on the server.
        const mod = await import("frappe-gantt");
        if (cancelled || !containerRef.current) return;
        const Ctor = (mod.default ?? mod) as unknown as GanttCtor;
        new Ctor(el, tasks, {
          view_mode: pickViewMode(tasks),
          bar_height: 20,
          padding: 18,
          popup_trigger: "click",
        });
        setReady(true);
      } catch (e) {
        // eslint-disable-next-line no-console
        console.error("GanttChart: failed to init", e);
        if (!cancelled) {
          setError(
            e instanceof Error ? e.message : "Couldn't render the Gantt chart.",
          );
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [tasks]);

  if (tasks.length === 0) {
    return (
      <div className="rounded-md bg-bg-tertiary p-4 text-callout text-label-secondary">
        No activities in this schedule yet.
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-md border border-separator/40 bg-bg-tertiary">
      <div ref={containerRef} className="min-w-[640px] p-2" aria-label="Schedule Gantt chart" />
      {!ready && !error && (
        <div className="p-3 text-footnote text-label-tertiary">Rendering schedule…</div>
      )}
      {error && (
        <div className="p-3 text-footnote text-danger">{error}</div>
      )}
    </div>
  );
}

function pickViewMode(tasks: GanttTask[]): GanttOptions["view_mode"] {
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
