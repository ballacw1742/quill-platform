// Ambient module declarations for frappe-gantt (no upstream @types package).
// We type only the surface area we use; the actual class API is permissive.

declare module "frappe-gantt" {
  export interface FrappeGanttTask {
    id: string;
    name: string;
    start: string;
    end: string;
    progress?: number;
    dependencies?: string;
    custom_class?: string;
  }

  export interface FrappeGanttOptions {
    view_mode?: "Quarter Day" | "Half Day" | "Day" | "Week" | "Month";
    bar_height?: number;
    padding?: number;
    language?: string;
    popup_trigger?: "click" | "mouseover";
    custom_popup_html?: ((task: unknown) => string) | null;
  }

  export default class Gantt {
    constructor(
      element: HTMLElement | SVGElement | string,
      tasks: FrappeGanttTask[],
      options?: FrappeGanttOptions,
    );
    refresh(tasks: FrappeGanttTask[]): void;
    change_view_mode(mode?: FrappeGanttOptions["view_mode"]): void;
  }
}


