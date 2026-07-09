"use client";

/**
 * /assistant/builder — Agent Builder (Phase C, agent-cloud/AGENT_BUILDER.md §10).
 *
 * A form + tool palette + templates + test console over the
 * agentcloud_agents row, through the JWT-gated api bridge. tenant_id never
 * appears here — the bridge injects it from the JWT (workspace=personal|org).
 *
 * NOTE ON ROUTE: the top-level /agents route is already the ADK Agent
 * Registry (Sprint DC.4). The builder lives under the assistant surface it
 * configures — /assistant/builder — to avoid colliding with that page.
 *
 * Sections:
 *  - agent list (seeds badged) + New agent (template picker)
 *  - editor form (slug/prompt/model/memory/budget/enabled + tool palette)
 *  - approval-queue notice when any write tool is enabled (APPROVALS.md)
 *  - test console (reuses the chat SSE against the SAVED agent)
 */

import * as React from "react";
import { toast } from "sonner";
import { ArrowLeft, History, Plus, ShieldAlert, Sparkles, Trash2, X } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { SegmentedControl } from "@/components/ui/segmented-control";
import {
  AgentCloudError,
  createAgent,
  deleteAgent,
  fetchAgentDetail,
  patchAgent,
  publishAgent,
  rollbackAgent,
  sendAgentChat,
  useAgentCloudAgents,
  useAgentCloudCatalog,
  useAgentCloudTemplates,
  useAgentVersionDiff,
  useAgentVersions,
  validateAgentDraft,
  type AgentDetail,
  type AgentVersionDiff,
  type AgentVersionItem,
  type Catalog,
  type Template,
} from "@/lib/agent-cloud";

const PROMPT_CAP = 8000;
const TENANT_CAP: Record<string, number> = { personal: 10, org: 100 };

type Draft = {
  agent_id: string;
  system_prompt: string;
  model: string;
  memory_policy: string;
  budget_monthly_usd: number;
  enabled: boolean;
  tools: string[];
  is_seed: boolean;
  published: boolean; // Phase 5 (AUTHORING_MATURITY.md §2.5)
};

const BLANK: Draft = {
  agent_id: "",
  system_prompt: "",
  model: "",
  memory_policy: "off",
  budget_monthly_usd: 10,
  enabled: true,
  tools: [],
  is_seed: false,
  published: false,
};

function draftFromDetail(a: AgentDetail): Draft {
  return {
    agent_id: a.agent_id,
    system_prompt: a.system_prompt,
    model: a.model,
    memory_policy: a.memory_policy,
    budget_monthly_usd: a.budget_monthly_usd,
    enabled: a.enabled,
    tools: [...a.tools],
    is_seed: a.is_seed,
    published: a.published ?? false,
  };
}

function draftFromTemplate(t: Template): Draft {
  return {
    agent_id: "",
    system_prompt: t.system_prompt,
    model: t.model,
    memory_policy: t.memory_policy,
    budget_monthly_usd: t.budget_monthly_usd,
    enabled: true,
    tools: [...t.tools],
    is_seed: false,
  };
}

export default function AgentBuilderPage() {
  const [workspace, setWorkspace] = React.useState("personal");
  const [selected, setSelected] = React.useState<string | null>(null); // agent_id being edited
  const [mode, setMode] = React.useState<"list" | "new" | "edit">("list");
  const [draft, setDraft] = React.useState<Draft>(BLANK);
  const [saving, setSaving] = React.useState(false);

  const agents = useAgentCloudAgents(workspace);
  const catalog = useAgentCloudCatalog(workspace);
  const templates = useAgentCloudTemplates(workspace);

  const tenantCap = TENANT_CAP[workspace] ?? 10;
  const hasWriteTool = React.useMemo(
    () => draftHasApprovalGated(draft.tools, catalog.data),
    [draft.tools, catalog.data],
  );

  async function openEdit(agentId: string) {
    setMode("edit");
    setSelected(agentId);
    try {
      const detail = await fetchAgentDetail(agentId, workspace);
      setDraft(draftFromDetail(detail));
    } catch (e) {
      toast.error(e instanceof AgentCloudError ? e.message : "Couldn't load agent");
      setMode("list");
    }
  }

  function openNew(t?: Template) {
    setMode("new");
    setSelected(null);
    setDraft(t ? draftFromTemplate(t) : { ...BLANK, model: catalog.data?.models[0] ?? "" });
  }

  function backToList() {
    setMode("list");
    setSelected(null);
    setDraft(BLANK);
  }

  async function save() {
    const err = validateAgentDraft(
      {
        agent_id: draft.agent_id,
        system_prompt: draft.system_prompt,
        budget_monthly_usd: draft.budget_monthly_usd,
      },
      { tenantCap, isEdit: mode === "edit", promptCap: PROMPT_CAP },
    );
    if (err) {
      toast.error(err);
      return;
    }
    setSaving(true);
    try {
      if (mode === "new") {
        const created = await createAgent(
          {
            agent_id: draft.agent_id,
            system_prompt: draft.system_prompt,
            model: draft.model || undefined,
            tools: draft.tools,
            memory_policy: draft.memory_policy,
            budget_monthly_usd: draft.budget_monthly_usd,
            enabled: draft.enabled,
          },
          workspace,
        );
        toast.success(`Created ${created.agent_id}`);
        await agents.refetch();
        void openEdit(created.agent_id);
      } else if (selected) {
        const patch: Record<string, unknown> = {
          system_prompt: draft.system_prompt,
          model: draft.model,
          tools: draft.tools,
          memory_policy: draft.memory_policy,
          budget_monthly_usd: draft.budget_monthly_usd,
        };
        // Only send enabled for non-seeds (seeds reject disable; harmless to omit).
        if (!draft.is_seed) patch.enabled = draft.enabled;
        const updated = await patchAgent(selected, patch, workspace);
        setDraft(draftFromDetail(updated));
        toast.success("Saved");
        await agents.refetch();
      }
    } catch (e) {
      toast.error(e instanceof AgentCloudError ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  async function onDelete() {
    if (!selected || draft.is_seed) return;
    if (!window.confirm(`Disable agent "${selected}"? Its history is kept.`)) return;
    try {
      await deleteAgent(selected, workspace);
      toast.success(`Disabled ${selected}`);
      await agents.refetch();
      backToList();
    } catch (e) {
      toast.error(e instanceof AgentCloudError ? e.message : "Delete failed");
    }
  }

  /** Called from VersionPanel after rollback or publish-toggle. */
  function onVersionChange(detail: AgentDetail) {
    setDraft(draftFromDetail(detail));
    void agents.refetch();
  }

  return (
    <div className="mx-auto flex min-h-screen w-full max-w-3xl flex-col gap-4 px-4 py-4">
      <header className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          {mode !== "list" ? (
            <button
              type="button"
              aria-label="Back"
              onClick={backToList}
              className="text-accent"
            >
              <ArrowLeft className="h-5 w-5" />
            </button>
          ) : (
            <a href="/assistant" aria-label="Assistant" className="text-accent">
              <ArrowLeft className="h-5 w-5" />
            </a>
          )}
          <h1 className="text-lg font-semibold">Agent Builder</h1>
        </div>
        <SegmentedControl
          ariaLabel="Workspace"
          value={workspace}
          onChange={(w) => {
            setWorkspace(w);
            backToList();
          }}
          options={[
            { value: "personal", label: "Personal" },
            { value: "org", label: "Org" },
          ]}
        />
      </header>

      {mode === "list" && (
        <AgentList
          agents={agents.data?.items ?? []}
          isLoading={agents.isLoading}
          isError={agents.isError}
          templates={templates.data?.templates ?? []}
          onEdit={openEdit}
          onNew={openNew}
        />
      )}

      {mode !== "list" && catalog.data && (
        <Editor
          draft={draft}
          setDraft={setDraft}
          catalog={catalog.data}
          tenantCap={tenantCap}
          isEdit={mode === "edit"}
          hasWriteTool={hasWriteTool}
          saving={saving}
          onSave={save}
          onDelete={onDelete}
          onVersionChange={onVersionChange}
          workspace={workspace}
          savedAgentId={mode === "edit" ? selected : null}
        />
      )}
    </div>
  );
}

function draftHasApprovalGated(tools: string[], catalog?: Catalog): boolean {
  if (!catalog) return false;
  const gated = new Set(
    catalog.groups.flatMap((g) => g.tools.filter((t) => t.approval_gated).map((t) => t.name)),
  );
  return tools.some((t) => gated.has(t));
}

// ─── Agent list + template picker ───────────────────────────────────────────

function AgentList(props: {
  agents: Array<{ agent_id: string; enabled: boolean; model: string; memory_policy: string }>;
  isLoading: boolean;
  isError: boolean;
  templates: Template[];
  onEdit: (id: string) => void;
  onNew: (t?: Template) => void;
}) {
  const SEEDS = new Set(["personal", "quill"]);
  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-medium text-muted-foreground">Your agents</h2>
        <Button size="sm" onClick={() => props.onNew()}>
          <Plus className="h-4 w-4" /> New agent
        </Button>
      </div>

      {props.isError && (
        <p className="text-sm text-destructive">Couldn&apos;t reach the agent service.</p>
      )}
      {props.isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}

      <ul className="flex flex-col gap-2">
        {props.agents.map((a) => (
          <li key={a.agent_id}>
            <button
              type="button"
              onClick={() => props.onEdit(a.agent_id)}
              className="flex w-full items-center justify-between rounded-lg border border-input bg-background px-3 py-3 text-left hover:bg-accent/40"
            >
              <span className="flex items-center gap-2">
                <span className="font-medium">{a.agent_id}</span>
                {SEEDS.has(a.agent_id) && <Badge variant="secondary">seed</Badge>}
                {!a.enabled && <Badge variant="muted">disabled</Badge>}
              </span>
              <span className="text-xs text-muted-foreground">{a.model}</span>
            </button>
          </li>
        ))}
      </ul>

      <div className="mt-2">
        <h2 className="mb-2 flex items-center gap-1 text-sm font-medium text-muted-foreground">
          <Sparkles className="h-4 w-4" /> Start from a template
        </h2>
        <div className="grid gap-2 sm:grid-cols-3">
          {props.templates.map((t) => (
            <button
              key={t.template_id}
              type="button"
              onClick={() => props.onNew(t)}
              className="flex flex-col gap-1 rounded-lg border border-input bg-background p-3 text-left hover:bg-accent/40"
            >
              <span className="font-medium">{t.name}</span>
              <span className="text-xs text-muted-foreground">{t.summary}</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

// ─── Editor ─────────────────────────────────────────────────────────────────

function Editor(props: {
  draft: Draft;
  setDraft: React.Dispatch<React.SetStateAction<Draft>>;
  catalog: Catalog;
  tenantCap: number;
  isEdit: boolean;
  hasWriteTool: boolean;
  saving: boolean;
  onSave: () => void;
  onDelete: () => void;
  onVersionChange: (detail: AgentDetail) => void;
  workspace: string;
  savedAgentId: string | null;
}) {
  const { draft, setDraft, catalog } = props;
  const set = <K extends keyof Draft>(k: K, v: Draft[K]) =>
    setDraft((d) => ({ ...d, [k]: v }));

  function toggleTool(name: string) {
    setDraft((d) => ({
      ...d,
      tools: d.tools.includes(name)
        ? d.tools.filter((t) => t !== name)
        : [...d.tools, name],
    }));
  }

  return (
    <div className="flex flex-col gap-4">
      {/* slug */}
      <div className="flex flex-col gap-1">
        <Label htmlFor="agent_id">Slug</Label>
        <Input
          id="agent_id"
          value={draft.agent_id}
          disabled={props.isEdit}
          placeholder="research-assistant"
          onChange={(e) => set("agent_id", e.target.value)}
        />
        {props.isEdit && (
          <p className="text-xs text-muted-foreground">
            Slug is immutable. {draft.is_seed && "This is a seed agent."}
          </p>
        )}
      </div>

      {/* system prompt */}
      <div className="flex flex-col gap-1">
        <div className="flex items-center justify-between">
          <Label htmlFor="system_prompt">System prompt</Label>
          <span
            className={
              "text-xs " +
              (draft.system_prompt.length > PROMPT_CAP
                ? "text-destructive"
                : "text-muted-foreground")
            }
          >
            {draft.system_prompt.length}/{PROMPT_CAP}
          </span>
        </div>
        <Textarea
          id="system_prompt"
          rows={6}
          value={draft.system_prompt}
          onChange={(e) => set("system_prompt", e.target.value)}
        />
      </div>

      {/* model + memory + budget */}
      <div className="grid gap-3 sm:grid-cols-3">
        <div className="flex flex-col gap-1">
          <Label>Model</Label>
          <Select value={draft.model} onValueChange={(v) => set("model", v)}>
            <SelectTrigger>
              <SelectValue placeholder="Pick a model" />
            </SelectTrigger>
            <SelectContent>
              {catalog.models.map((m) => (
                <SelectItem key={m} value={m}>
                  {m}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex flex-col gap-1">
          <Label>Memory</Label>
          <Select
            value={draft.memory_policy}
            onValueChange={(v) => set("memory_policy", v)}
          >
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {catalog.memory_policies.map((p) => (
                <SelectItem key={p} value={p}>
                  {p}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex flex-col gap-1">
          <Label htmlFor="budget">Budget (USD/mo)</Label>
          <Input
            id="budget"
            type="number"
            min={0}
            step="0.5"
            value={draft.budget_monthly_usd}
            onChange={(e) => set("budget_monthly_usd", Number(e.target.value))}
          />
          <p className="text-xs text-muted-foreground">Cap ${props.tenantCap}</p>
        </div>
      </div>

      {/* enabled toggle (disabled for seeds) */}
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={draft.enabled}
          disabled={draft.is_seed}
          onChange={(e) => set("enabled", e.target.checked)}
        />
        Enabled
        {draft.is_seed && (
          <span className="text-xs text-muted-foreground">(seeds can&apos;t be disabled)</span>
        )}
      </label>

      {/* tool palette */}
      <div className="flex flex-col gap-3">
        <h3 className="text-sm font-medium">Tools</h3>
        {props.hasWriteTool && (
          <div className="flex items-start gap-2 rounded-md border border-warning/40 bg-warning/10 p-2 text-xs text-foreground">
            <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
            <span>
              Write tools never change Quill directly — every action is queued for
              human approval in the Quill queue.
            </span>
          </div>
        )}
        {catalog.groups.map((g) => (
          <fieldset key={g.group} className="flex flex-col gap-1">
            <legend className="mb-1 text-xs font-medium text-muted-foreground">
              {g.label}
            </legend>
            <div className="flex flex-col gap-1">
              {g.tools.map((t) => (
                <label
                  key={t.name}
                  className="flex items-start gap-2 rounded-md px-1 py-1 text-sm hover:bg-accent/30"
                >
                  <input
                    type="checkbox"
                    className="mt-1"
                    checked={draft.tools.includes(t.name)}
                    onChange={() => toggleTool(t.name)}
                  />
                  <span className="flex flex-col">
                    <span className="flex items-center gap-1">
                      {t.label}
                      {t.approval_gated && (
                        <Badge variant="warning">approval</Badge>
                      )}
                      {t.memory_tool && <Badge variant="muted">memory</Badge>}
                    </span>
                    <span className="text-xs text-muted-foreground">{t.description}</span>
                  </span>
                </label>
              ))}
            </div>
          </fieldset>
        ))}
      </div>

      {/* actions */}
      <div className="flex items-center gap-2">
        <Button onClick={props.onSave} disabled={props.saving}>
          {props.saving ? "Saving…" : props.isEdit ? "Save" : "Create"}
        </Button>
        {props.isEdit && !draft.is_seed && (
          <Button variant="destructive" onClick={props.onDelete}>
            <Trash2 className="h-4 w-4" /> Disable
          </Button>
        )}
      </div>

      {/* test console (only for a saved agent) */}
      {props.savedAgentId ? (
        <TestConsole agentId={props.savedAgentId} workspace={props.workspace} />
      ) : (
        <p className="text-xs text-muted-foreground">Save to test this agent.</p>
      )}

      {/* version history panel (only for a saved agent) */}
      {props.savedAgentId && (
        <VersionPanel
          agentId={props.savedAgentId}
          workspace={props.workspace}
          published={props.draft.published}
          onVersionChange={props.onVersionChange}
        />
      )}
    </div>
  );
}

// ─── Test console ───────────────────────────────────────────────────────────

function TestConsole(props: { agentId: string; workspace: string }) {
  const [msg, setMsg] = React.useState("");
  const [log, setLog] = React.useState<Array<{ role: string; text: string }>>([]);
  const [busy, setBusy] = React.useState(false);
  const sessionRef = React.useRef<string | null>(null);

  async function send() {
    const text = msg.trim();
    if (!text || busy) return;
    setMsg("");
    setBusy(true);
    setLog((l) => [...l, { role: "user", text }]);
    let reply = "";
    let err: string | null = null;
    try {
      await sendAgentChat(
        {
          agentId: props.agentId,
          message: text,
          sessionId: sessionRef.current,
          workspace: props.workspace,
        },
        {
          onEvent: (ev) => {
            if (ev.type === "session") sessionRef.current = ev.session_id;
            else if (ev.type === "text") reply += ev.delta;
            else if (ev.type === "done") reply = ev.result.reply || reply;
            else if (ev.type === "error") err = ev.detail;
          },
        },
      );
    } catch (e) {
      err = e instanceof AgentCloudError ? e.message : "Connection failed.";
    }
    setLog((l) => [...l, { role: "assistant", text: err ? `Error: ${err}` : reply }]);
    setBusy(false);
  }

  return (
    <div className="mt-2 flex flex-col gap-2 rounded-lg border border-input p-3">
      <h3 className="text-sm font-medium">Test console</h3>
      <div className="flex max-h-64 flex-col gap-2 overflow-y-auto">
        {log.map((m, i) => (
          <div
            key={i}
            className={
              "rounded-md px-2 py-1 text-sm " +
              (m.role === "user"
                ? "self-end bg-primary/10"
                : "self-start bg-muted")
            }
          >
            {m.text}
          </div>
        ))}
        {log.length === 0 && (
          <p className="text-xs text-muted-foreground">
            Try the saved agent before shipping it.
          </p>
        )}
      </div>
      <div className="flex items-center gap-2">
        <Input
          value={msg}
          placeholder="Message this agent…"
          disabled={busy}
          onChange={(e) => setMsg(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") send();
          }}
        />
        <Button size="sm" onClick={send} disabled={busy}>
          Send
        </Button>
      </div>
    </div>
  );
}

// ─── VersionPanel ──────────────────────────────────────────────────────────────────

/**
 * Version history, diff viewer, rollback, and publish toggle for a saved agent.
 * AUTHORING_MATURITY.md §7.
 */
function VersionPanel(props: {
  agentId: string;
  workspace: string;
  published: boolean;
  onVersionChange: (detail: AgentDetail) => void;
}) {
  const [diffPair, setDiffPair] = React.useState<[number, number] | null>(null);
  const [rollingBack, setRollingBack] = React.useState<number | null>(null);
  const [toggling, setToggling] = React.useState(false);

  const versions = useAgentVersions(props.agentId, props.workspace);
  const items: AgentVersionItem[] = versions.data?.items ?? [];
  const currentVersion = items.find((i) => i.is_current)?.version ?? null;

  async function doRollback(toVersion: number) {
    if (
      !window.confirm(
        `Roll back to v${toVersion}? A new version is created — history is never lost.`,
      )
    )
      return;
    setRollingBack(toVersion);
    try {
      const detail = await rollbackAgent(props.agentId, toVersion, props.workspace);
      toast.success(`Rolled back → now at v${detail.version ?? "?"}`);
      void versions.refetch();
      setDiffPair(null);
      props.onVersionChange(detail);
    } catch (e) {
      toast.error(e instanceof AgentCloudError ? e.message : "Rollback failed");
    } finally {
      setRollingBack(null);
    }
  }

  async function doPublishToggle() {
    setToggling(true);
    try {
      const detail = await publishAgent(
        props.agentId,
        !props.published,
        props.workspace,
      );
      toast.success(detail.published ? "Published to workspace" : "Unpublished");
      props.onVersionChange(detail);
    } catch (e) {
      toast.error(e instanceof AgentCloudError ? e.message : "Publish toggle failed");
    } finally {
      setToggling(false);
    }
  }

  function toggleDiff(version: number) {
    if (!currentVersion || version === currentVersion) return;
    setDiffPair((pair) =>
      pair && pair[0] === version ? null : [version, currentVersion],
    );
  }

  if (versions.isLoading)
    return (
      <div className="mt-2 rounded-lg border border-input p-3">
        <p className="text-xs text-muted-foreground">Loading history…</p>
      </div>
    );
  if (versions.isError)
    return (
      <div className="mt-2 rounded-lg border border-input p-3">
        <p className="text-xs text-destructive">Couldn&apos;t load version history.</p>
      </div>
    );

  return (
    <div className="mt-2 flex flex-col gap-3 rounded-lg border border-input p-3">
      {/* header + publish toggle */}
      <div className="flex items-center justify-between gap-2">
        <h3 className="flex items-center gap-1.5 text-sm font-medium">
          <History className="h-4 w-4" />
          Version history
          {items.length > 0 && (
            <span className="text-xs font-normal text-muted-foreground">
              ({items.length})
            </span>
          )}
        </h3>
        <label className="flex cursor-pointer select-none items-center gap-1.5 text-xs">
          <input
            type="checkbox"
            checked={props.published}
            disabled={toggling}
            onChange={doPublishToggle}
            className="cursor-pointer"
          />
          <span>
            Publish
            <span className="ml-1 text-muted-foreground">(workspace-visible)</span>
          </span>
        </label>
      </div>

      {items.length === 0 && (
        <p className="text-xs text-muted-foreground">No version history yet.</p>
      )}

      {/* version list */}
      <ul className="flex flex-col gap-1.5">
        {items.map((v) => (
          <li key={v.version} className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
            <span className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-sm">
              <span className="font-mono text-xs tabular-nums text-foreground">
                v{v.version}
              </span>
              {v.is_current && <Badge variant="secondary">current</Badge>}
              <span className="text-xs capitalize text-muted-foreground">
                {v.change_action}
              </span>
              {v.rolled_back_from !== null && (
                <span className="text-xs text-muted-foreground">
                  (from v{v.rolled_back_from})
                </span>
              )}
              <span className="text-xs text-muted-foreground">
                {new Date(v.created_at).toLocaleDateString(undefined, {
                  month: "short",
                  day: "numeric",
                })}
              </span>
              {v.changed_fields.length > 0 &&
                !v.changed_fields.includes("*") && (
                  <span className="text-xs text-muted-foreground">
                    · {v.changed_fields.join(", ")}
                  </span>
                )}
            </span>
            <span className="flex shrink-0 items-center gap-2">
              {!v.is_current && currentVersion !== null && (
                <button
                  type="button"
                  onClick={() => toggleDiff(v.version)}
                  className={
                    "text-xs underline-offset-2 hover:underline " +
                    (diffPair?.[0] === v.version
                      ? "font-medium text-accent"
                      : "text-accent")
                  }
                >
                  {diffPair?.[0] === v.version ? "hide diff" : "diff"}
                </button>
              )}
              {!v.is_current && (
                <button
                  type="button"
                  disabled={rollingBack !== null}
                  onClick={() => doRollback(v.version)}
                  className="text-xs text-destructive underline-offset-2 hover:underline disabled:opacity-50"
                >
                  {rollingBack === v.version ? "…" : "rollback"}
                </button>
              )}
            </span>
          </li>
        ))}
      </ul>

      {/* diff view */}
      {diffPair && (
        <DiffView
          agentId={props.agentId}
          from={diffPair[0]}
          to={diffPair[1]}
          workspace={props.workspace}
          onClose={() => setDiffPair(null)}
        />
      )}
    </div>
  );
}

// ─── DiffView ───────────────────────────────────────────────────────────────────────

function DiffView(props: {
  agentId: string;
  from: number;
  to: number;
  workspace: string;
  onClose: () => void;
}) {
  const diff = useAgentVersionDiff(props.agentId, props.from, props.to, props.workspace);

  return (
    <div className="rounded-md border border-input bg-muted/30 p-3 text-xs">
      <div className="mb-2 flex items-center justify-between">
        <span className="font-medium">
          v{props.from} → v{props.to} (current)
        </span>
        <button
          type="button"
          onClick={props.onClose}
          aria-label="Close diff"
          className="text-muted-foreground hover:text-foreground"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      {diff.isLoading && (
        <p className="text-muted-foreground">Loading diff…</p>
      )}
      {diff.isError && (
        <p className="text-destructive">Couldn&apos;t load diff.</p>
      )}
      {diff.data && diff.data.changes.length === 0 && (
        <p className="text-muted-foreground">No differences between these versions.</p>
      )}
      {diff.data &&
        diff.data.changes.map((c) => (
          <div key={c.field} className="mb-2 last:mb-0">
            <div className="mb-1 font-semibold text-foreground">{c.field}</div>
            <div className="grid grid-cols-2 gap-2">
              <div className="overflow-x-auto rounded bg-destructive/10 p-1.5 font-mono">
                <span className="text-destructive">− </span>
                {formatDiffValue(c.from)}
              </div>
              <div className="overflow-x-auto rounded bg-green-500/10 p-1.5 font-mono">
                <span className="text-green-600">+ </span>
                {formatDiffValue(c.to)}
              </div>
            </div>
          </div>
        ))}
    </div>
  );
}

/** Render a diff value as a compact display string. Truncates long text. */
function formatDiffValue(v: unknown): string {
  if (typeof v === "string") {
    return v.length > 200 ? v.slice(0, 200) + "…" : v || "(empty)";
  }
  if (Array.isArray(v)) {
    const parts = v.map(String);
    return parts.length > 0 ? parts.join(", ") : "(none)";
  }
  if (v === null || v === undefined) return "(null)";
  return String(JSON.stringify(v));
}
