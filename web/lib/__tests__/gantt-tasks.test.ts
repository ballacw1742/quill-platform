import { describe, it, expect } from "vitest";
import { activitiesToGanttTasks } from "../../components/estimates/gantt-tasks";

const MS_PER_DAY = 86_400_000;

describe("activitiesToGanttTasks", () => {
  it("returns [] when the schedule has no activities", () => {
    expect(
      activitiesToGanttTasks({
        level: 1,
        activities: [],
        total_duration_days: 0,
      }),
    ).toEqual([]);
  });

  it("anchors a single activity at today and produces a valid date range", () => {
    const tasks = activitiesToGanttTasks({
      level: 1,
      activities: [
        { id: "A1", name: "Site mob", duration_days: 5 },
      ],
      total_duration_days: 5,
    });
    expect(tasks).toHaveLength(1);
    const t = tasks[0];
    expect(t.id).toBe("A1");
    const start = Date.parse(t.start);
    const end = Date.parse(t.end);
    expect(end - start).toBe(4 * MS_PER_DAY); // inclusive end
  });

  it("honours FS predecessors with lag_days", () => {
    const tasks = activitiesToGanttTasks({
      level: 2,
      activities: [
        { id: "A1", name: "Mob", duration_days: 10 },
        {
          id: "A2",
          name: "Switchgear procurement",
          duration_days: 30,
          predecessors: [{ id: "A1", type: "FS", lag_days: 5 }],
        },
      ],
      total_duration_days: 45,
    });
    const a1 = tasks.find((t) => t.id === "A1")!;
    const a2 = tasks.find((t) => t.id === "A2")!;
    // A2 should start 10 (A1 dur) + 5 (lag) days after A1 starts.
    const a1Start = Date.parse(a1.start);
    const a2Start = Date.parse(a2.start);
    expect(a2Start - a1Start).toBe(15 * MS_PER_DAY);
  });

  it("emits dependencies as a comma-separated id list", () => {
    const tasks = activitiesToGanttTasks({
      level: 2,
      activities: [
        { id: "A1", name: "x", duration_days: 1 },
        { id: "A2", name: "y", duration_days: 1 },
        {
          id: "A3",
          name: "z",
          duration_days: 1,
          predecessors: [
            { id: "A1", type: "FS" },
            { id: "A2", type: "FS" },
          ],
        },
      ],
      total_duration_days: 3,
    });
    const a3 = tasks.find((t) => t.id === "A3")!;
    expect(a3.dependencies).toBe("A1,A2");
  });

  it("flags critical-path activities with a custom_class", () => {
    const tasks = activitiesToGanttTasks({
      level: 3,
      activities: [
        { id: "A1", name: "x", duration_days: 1, critical_path: true },
        { id: "A2", name: "y", duration_days: 1, milestone: true },
      ],
      total_duration_days: 2,
    });
    expect(tasks.find((t) => t.id === "A1")?.custom_class).toBe("gantt-critical");
    expect(tasks.find((t) => t.id === "A2")?.custom_class).toBe("gantt-milestone");
  });
});
