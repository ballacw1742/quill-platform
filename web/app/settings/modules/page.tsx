"use client";

/**
 * /settings/modules — Modular Framework Phase 0 (MODULAR_FRAMEWORK_DESIGN.md §5).
 *
 * Per-workspace module management: enable/disable each home-screen module and
 * reorder them. Mutations are owner-only (the server enforces 403; the UI also
 * hides the controls for non-owners and shows a read-only note).
 *
 * Reorder is done with up/down controls (no drag-drop dependency) — simple,
 * accessible, and mobile-friendly. Each change PATCHes the affected module(s);
 * the home screen picks up the new config on its next load.
 */

import * as React from "react";
import { toast } from "sonner";
import { ChevronDown, ChevronUp, GripVertical, Plus, Trash2 } from "lucide-react";
import { MobileShell, TopBar, BackButton } from "@/components/layout/MobileShell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  useCreateCustomModule,
  useDeleteCustomModule,
  useModuleConfig,
  useSession,
  useUpdateModuleConfig,
  type ModuleConfigItem,
  type ModuleUpdate,
} from "@/lib/api";
import type { Session } from "@/lib/schemas";
import { cn } from "@/lib/utils";

export default function ModulesSettingsPage() {
  return (
    <MobileShell>
      <TopBar
        title="Modules"
        left={<BackButton href="/settings" label="Settings" />}
      />
      <ModulesManager />
    </MobileShell>
  );
}

function ModulesManager() {
  const { data: rawSession } = useSession();
  const session = rawSession as Session | null | undefined;
  const isOwner = session?.role === "owner";

  const { data, isLoading, isError } = useModuleConfig();
  const update = useUpdateModuleConfig();
  const createCustom = useCreateCustomModule();
  const deleteCustom = useDeleteCustomModule();

  const [showNew, setShowNew] = React.useState(false);
  const [newKey, setNewKey] = React.useState("");
  const [newLabel, setNewLabel] = React.useState("");

  function createModule() {
    const key = newKey.trim().toLowerCase();
    const label = newLabel.trim();
    if (!/^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$/.test(key)) {
      toast.error("Key must be a lowercase slug (letters, digits, hyphens).");
      return;
    }
    if (!label) {
      toast.error("Give the module a name.");
      return;
    }
    createCustom.mutate(
      { key, label },
      {
        onSuccess: () => {
          toast.success(`Created ${label}`);
          setNewKey("");
          setNewLabel("");
          setShowNew(false);
        },
        onError: (e) =>
          toast.error(e instanceof Error ? e.message : "Couldn't create module"),
      },
    );
  }

  function removeCustom(key: string, label: string) {
    if (!window.confirm(`Delete the "${label}" module? This can't be undone.`)) return;
    deleteCustom.mutate(
      { key },
      {
        onSuccess: () => toast.success(`Deleted ${label}`),
        onError: (e) =>
          toast.error(e instanceof Error ? e.message : "Couldn't delete module"),
      },
    );
  }

  // Local working copy so reordering feels instant; server is source of truth
  // and we re-sync from the mutation response.
  const [items, setItems] = React.useState<ModuleConfigItem[] | null>(null);
  React.useEffect(() => {
    if (data?.items) setItems(data.items);
  }, [data]);

  const rows = items ?? [];

  function persist(updates: ModuleUpdate[]) {
    update.mutate(
      { updates },
      {
        onSuccess: (res) => setItems(res.items),
        onError: (e) => {
          toast.error(e instanceof Error ? e.message : "Couldn't save changes");
          // resync from server truth
          if (data?.items) setItems(data.items);
        },
      },
    );
  }

  function toggle(key: string, enabled: boolean) {
    setItems((prev) =>
      (prev ?? []).map((r) => (r.key === key ? { ...r, enabled } : r)),
    );
    persist([{ key, enabled }]);
  }

  function toggleFeature(moduleKey: string, featureKey: string, enabled: boolean) {
    setItems((prev) =>
      (prev ?? []).map((r) =>
        r.key === moduleKey
          ? {
              ...r,
              features: r.features.map((f) =>
                f.key === featureKey ? { ...f, enabled } : f,
              ),
            }
          : r,
      ),
    );
    persist([{ key: moduleKey, features: { [featureKey]: enabled } }]);
  }

  function move(index: number, dir: -1 | 1) {
    const next = [...rows];
    const target = index + dir;
    if (target < 0 || target >= next.length) return;
    [next[index], next[target]] = [next[target], next[index]];
    // Renumber sort_order to the new positions and persist both moved rows.
    const renumbered = next.map((r, i) => ({ ...r, sort_order: i }));
    setItems(renumbered);
    persist([
      { key: renumbered[index].key, sort_order: index },
      { key: renumbered[target].key, sort_order: target },
    ]);
  }

  if (isLoading) {
    return <p className="px-4 py-6 text-sm text-label-secondary">Loading modules…</p>;
  }
  if (isError) {
    return (
      <p className="px-4 py-6 text-sm text-danger">
        Couldn&apos;t load module settings. Pull to refresh or try again.
      </p>
    );
  }

  return (
    <div className="mx-auto w-full max-w-2xl px-4 py-4">
      <p className="mb-4 text-footnote text-label-secondary">
        {isOwner
          ? "Turn modules on or off and reorder how they appear on your home screen. Disabled modules are hidden from the grid."
          : "This is a read-only view. Only the workspace owner can change module settings."}
      </p>

      <ul className="flex flex-col divide-y divide-separator/40 overflow-hidden rounded-2xl border border-separator/40 bg-bg-elevated/40">
        {rows.map((m, i) => (
          <li
            key={m.key}
            className={cn(
              "flex flex-col px-3 py-3",
              !m.enabled && "opacity-55",
            )}
          >
            <div className="flex items-center gap-3">
            {isOwner && (
              <div className="flex flex-col">
                <button
                  type="button"
                  aria-label={`Move ${m.label} up`}
                  disabled={i === 0 || update.isPending}
                  onClick={() => move(i, -1)}
                  className="text-label-secondary disabled:opacity-30 active:opacity-60 no-tap-highlight"
                >
                  <ChevronUp className="h-4 w-4" />
                </button>
                <button
                  type="button"
                  aria-label={`Move ${m.label} down`}
                  disabled={i === rows.length - 1 || update.isPending}
                  onClick={() => move(i, 1)}
                  className="text-label-secondary disabled:opacity-30 active:opacity-60 no-tap-highlight"
                >
                  <ChevronDown className="h-4 w-4" />
                </button>
              </div>
            )}
            {!isOwner && (
              <GripVertical className="h-4 w-4 text-label-tertiary" aria-hidden="true" />
            )}

            <span className="flex-1 text-body font-medium text-label-primary">
              {m.label}
              {m.custom && (
                <span className="ml-2 rounded bg-accent/10 px-1.5 py-0.5 text-caption-2 text-accent align-middle">
                  custom
                </span>
              )}
            </span>

            {isOwner && m.custom && (
              <button
                type="button"
                aria-label={`Delete ${m.label}`}
                onClick={() => removeCustom(m.key, m.label)}
                disabled={deleteCustom.isPending}
                className="text-danger/70 active:opacity-60 no-tap-highlight"
              >
                <Trash2 className="h-4 w-4" />
              </button>
            )}

            <Toggle
              checked={m.enabled}
              disabled={!isOwner || update.isPending}
              onChange={(v) => toggle(m.key, v)}
              label={`${m.enabled ? "Disable" : "Enable"} ${m.label}`}
            />
            </div>

            {/* Sub-feature toggles (Phase 1) — only when the module is on and
                has a fixed feature list. Disabling a feature skips just that
                part of the module's pipeline. */}
            {m.enabled && m.features.length > 0 && (
              <ul className="mt-1 flex flex-col gap-1 border-t border-separator/30 pt-2 pl-9">
                {m.features.map((f) => (
                  <li key={f.key} className="flex items-center gap-3 py-1">
                    <span className="flex-1 text-footnote text-label-secondary">
                      {f.label}
                    </span>
                    <Toggle
                      checked={f.enabled}
                      disabled={!isOwner || update.isPending}
                      onChange={(v) => toggleFeature(m.key, f.key, v)}
                      label={`${f.enabled ? "Disable" : "Enable"} ${f.label} in ${m.label}`}
                    />
                  </li>
                ))}
              </ul>
            )}
          </li>
        ))}
      </ul>

      {isOwner && (
        <div className="mt-4">
          {!showNew ? (
            <Button size="sm" variant="secondary" onClick={() => setShowNew(true)}>
              <Plus className="h-4 w-4" /> New module
            </Button>
          ) : (
            <div className="flex flex-col gap-2 rounded-2xl border border-separator/40 bg-bg-elevated/40 p-3">
              <p className="text-footnote text-label-secondary">
                Create a custom module. Key is a lowercase slug (e.g.
                &ldquo;permits&rdquo;); the name is what shows on the home grid.
              </p>
              <Input
                placeholder="key (e.g. permits)"
                value={newKey}
                onChange={(e) => setNewKey(e.target.value)}
              />
              <Input
                placeholder="Name (e.g. Permits)"
                value={newLabel}
                onChange={(e) => setNewLabel(e.target.value)}
              />
              <div className="flex gap-2">
                <Button size="sm" onClick={createModule} disabled={createCustom.isPending}>
                  {createCustom.isPending ? "Creating…" : "Create"}
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    setShowNew(false);
                    setNewKey("");
                    setNewLabel("");
                  }}
                >
                  Cancel
                </Button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/** Minimal accessible switch (no dedicated primitive exists in the kit). */
function Toggle(props: {
  checked: boolean;
  disabled?: boolean;
  onChange: (v: boolean) => void;
  label: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={props.checked}
      aria-label={props.label}
      disabled={props.disabled}
      onClick={() => props.onChange(!props.checked)}
      className={cn(
        "relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors no-tap-highlight",
        props.checked ? "bg-accent" : "bg-separator",
        props.disabled && "opacity-40",
      )}
    >
      <span
        className={cn(
          "inline-block h-5 w-5 transform rounded-full bg-white shadow transition-transform",
          props.checked ? "translate-x-[22px]" : "translate-x-0.5",
        )}
      />
    </button>
  );
}
