"use client";

import * as React from "react";
import "./frappe-gantt.css";
import type { ScheduleBlock } from "@/lib/schemas";
import {
  activitiesToGanttTasks,
  pickViewMode,
  type GanttTask,
} from "./gantt-tasks";

type GanttCtor = new (
  el: HTMLElement | SVGElement | string,
  tasks: GanttTask[],
  options?: GanttOptions,
) => unknown;

type GanttOptions = {
  view_mode?: "Quarter Day" | "Half Day" | "Day" | "Week" | "Month";
  bar_height?: number;
  padding?: number;
  language?: string;
  popup_trigger?: "click" | "mouseover";
  custom_popup_html?: ((task: unknown) => string) | null;
};

export { activitiesToGanttTasks } from "./gantt-tasks";

export function GanttChart({ schedule }: { schedule: ScheduleBlock }) {
  const containerRef = React.useRef<HTMLDivElement | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [ready, setReady] = React.useState(false);
  const tasks = React.useMemo(() => activitiesToGanttTasks(schedule), [schedule]);

  React.useEffect(() => {
    let cancelled = false;
    if (!containerRef.current) return;
    const el = containerRef.current;
    el.innerHTML = "";
    if (tasks.length === 0) {
      setReady(true);
      return;
    }

    (async () => {
      try {
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
