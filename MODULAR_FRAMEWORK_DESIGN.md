# Modular Framework — Design Proposal (DRAFT for Charles)

**Status:** Proposal / RFC — not yet approved or built. Author: Axe, 2026-07-09.
**Origin:** Charles's vision (2026-07-09): make modules plug-and-play so a project
can turn whole modules or *parts* of modules on/off, skip disabled steps to save
time, create net-new modules, and edit existing ones — a framework that adapts
across project **types** and **sizes** while keeping full agent-creation.

---

## 1. The vision in one line

> Turn Quill from a fixed 15-module app into a **configurable platform** where each
> tenant/project composes only the modules (and sub-features) it needs — disabled
> parts are skipped end-to-end (UI + pipeline + agents), and new modules can be
> authored without a code deploy.

---

## 2. Where we are today (honest current state)

| Layer | Today | Gap vs. vision |
|---|---|---|
| **Module roster** | Static, hard-coded list of 15 in `web/lib/modules.ts`, "order/names locked by UI brief". | Not data-driven, not per-tenant, can't add/remove/reorder without a code change. |
| **Home grid** | Renders all 15 tiles unconditionally (`app/page.tsx`). | No enable/disable; everyone sees everything. |
| **Pipeline / process** | Lifecycle + orchestrator run a fixed flow (project lifecycle stages, triage → dispatch). | No notion of "this module is off, skip its stage." |
| **Agents** | Fully dynamic already — create/edit/version/publish via Agent Builder (Phase C + Phase 5). ✅ | This is the model to copy for modules. |
| **Sub-features** | Each module page is a monolith. | No toggle for "only part of Contracts," etc. |

**Key insight:** Agents are *already* data-driven, tenant-scoped, and CRUD-able
(agentcloud_agents + versioning). Modules should follow the **same proven pattern**
— that de-risks the whole thing.

---

## 3. Proposed model

### 3.1 Module = data, not code (like agents)
Introduce a tenant-scoped `modules` config (new table `agentcloud_modules` or a
`workspace_config` doc), each row:

```
module_key        stable id (e.g. "contracts")
label, icon, gradient, href
enabled           bool  (tenant can turn the whole module off)
order             int   (tenant can reorder the home grid)
kind              "builtin" | "custom"
features[]        sub-feature toggles (see 3.2)
pipeline_stages[] which lifecycle/pipeline stages this module owns (see 3.3)
```

The 15 current modules seed as `builtin` rows (enabled by default) so nothing
changes for existing tenants — pure additive migration, same discipline as every
agentcloud_* column we've shipped.

### 3.2 Sub-feature toggles ("only need parts of a module")
Each module declares a set of named `features`. Example — Contracts:
`{ change_orders, clause_library, templates, e_sign }`. A tenant can disable
`e_sign` alone. The module page reads its feature flags and hides/skips disabled
parts; the pipeline skips steps whose feature is off.

### 3.3 Disabled = skipped end-to-end (the "save time" payoff)
The real value isn't just hiding a tile — it's the **pipeline honoring the config**:
- The orchestrator/lifecycle consults the tenant module config before running a
  stage. If the owning module (or the specific feature) is off → that stage is
  **skipped** (logged as "skipped: module disabled"), not run.
- Agents scoped to a disabled module aren't dispatched.
- This is where the time/cost savings come from.

### 3.4 Create / edit modules (no-deploy authoring)
Mirror the Agent Builder:
- A **Module Builder** UI (under `/assistant` or a new `/settings/modules`).
- Create a `custom` module: key, label, icon, gradient, which agents/pipeline
  stages it wires, its feature list.
- Edit/enable/disable/reorder builtins and customs.
- **Versioned + approval-gated** exactly like agents (reuse Phase 5 machinery) so
  a bad module change is rollback-able and never silently reshapes prod.

### 3.5 Full agent creation stays intact
Nothing here removes the current agent builder. Modules become the *organizing
layer* agents attach to; creating agents works exactly as today.

---

## 4. Framework-across-project-types angle

Once modules are data, **project templates** fall out naturally: a "Small Reno"
template enables {Requests, Projects, Documents, Approvals}; a "Data Center Dev"
template enables the full 15 + custom modules. Selecting a template = applying a
module-config preset. This is the "coalesce into a framework across project
types/sizes" Charles described.

---

## 5. Phasing (each phase independently shippable + verifiable)

- **Phase 0 — Data-drive the roster (low risk, high clarity).** Move the 15 from
  hard-coded to a seeded config; home grid reads `enabled` + `order`. Add a simple
  enable/disable + reorder UI in settings. *No pipeline change yet — just the UI
  becomes configurable.* Ships the "turn a module off" experience immediately.
- **Phase 1 — Sub-feature flags.** Add `features[]`; wire the 2–3 highest-value
  modules to actually read them.
- **Phase 2 — Pipeline honors config (the time-saver).** Orchestrator/lifecycle
  skip disabled modules/features/stages. Highest value, highest care — this is
  execution-path + safety-sensitive, so it gets the belt-and-suspenders + tests.
- **Phase 3 — Module Builder (create/edit) + versioning.** Reuse Phase 5.
- **Phase 4 — Project templates / presets** across types & sizes.

---

## 6. Decisions I need from Charles before building

1. **Scope of "module":** is a module primarily a *UI section* (a page + its
   agents), or also a *pipeline owner* (owns lifecycle stages)? My proposal treats
   it as both — confirm.
2. **Granularity of sub-features:** do you want arbitrary user-defined sub-features,
   or a fixed feature list per builtin module that you toggle? (Fixed is much
   simpler + safer to start; custom sub-features later.)
3. **Who can toggle:** owner-only, or any workspace member? (I'd default owner-only
   for disabling, given the pipeline-skip blast radius.)
4. **Config granularity:** per-**tenant/workspace**, or per-**project**? Per-project
   is more powerful (a template per project) but a bigger data model. I lean
   per-workspace first, per-project in Phase 4 with templates.
5. **Start point:** approve **Phase 0** (data-drive + enable/disable/reorder UI) as
   the first shippable slice, or do you want the full design nailed down first?

---

## 7. Why this order / why safe

- Every phase is additive and independently verifiable (build + tests), same
  discipline as the §9 merges and Phase 5.
- Phase 0 changes zero behavior for existing tenants (seed all-enabled) — it just
  *unlocks* configurability.
- The scary part (pipeline skipping stages) is isolated to Phase 2 with its own
  safety review — we don't touch the execution path until the config model is
  proven in the UI.
- Reuses the already-shipped, already-verified agent versioning/approval machinery
  for module authoring — minimal new risk surface.
