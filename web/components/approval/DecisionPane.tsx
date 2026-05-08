"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { ArrowUpFromLine, Check, Pencil, X } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { PasskeyChallengeModal } from "./PasskeyChallengeModal";
import { EditPayloadDialog } from "./EditPayloadDialog";
import { useDecide } from "@/lib/api";
import type { ActionIntent } from "@/lib/auth";
import { toast } from "sonner";
import type { ApprovalItem } from "@/lib/schemas";

type Mode = "approve" | "edit-then-approve" | "reject" | "escalate" | null;

const apiDecisionFor = (mode: Mode): ActionIntent["decision"] | null => {
  switch (mode) {
    case "approve":
      return "approve";
    case "edit-then-approve":
      return "edit_then_approve";
    case "reject":
      return "reject";
    case "escalate":
      return "escalate";
    default:
      return null;
  }
};

const wireDecisionFor = (
  mode: Mode,
): "approved" | "rejected" | "escalated" | null => {
  switch (mode) {
    case "approve":
    case "edit-then-approve":
      return "approved";
    case "reject":
      return "rejected";
    case "escalate":
      return "escalated";
    default:
      return null;
  }
};

export function DecisionPane({ item }: { item: ApprovalItem }) {
  const router = useRouter();
  const decide = useDecide();
  const [mode, setMode] = React.useState<Mode>(null);
  const [editOpen, setEditOpen] = React.useState(false);
  const [editedPayload, setEditedPayload] = React.useState<Record<
    string,
    unknown
  > | null>(null);
  const [reason, setReason] = React.useState("");
  const [passkeyOpen, setPasskeyOpen] = React.useState(false);

  const isPending = item.status === "pending";

  const finish = (verb: string) => {
    toast.success(`${verb} ${item.approval_id.slice(0, 18)}…`);
    router.push("/queue");
  };

  const buildIntent = React.useCallback((): ActionIntent | null => {
    const decision = apiDecisionFor(mode);
    if (!decision) return null;
    return {
      approval_id: item.approval_id,
      decision,
      edits: editedPayload,
      rejection_reason:
        mode === "reject" || mode === "escalate" ? reason || null : null,
      escalate_to_lane: null,
    };
  }, [mode, item.approval_id, editedPayload, reason]);

  const triggerPasskey = (m: Exclude<Mode, null>) => {
    setMode(m);
    setPasskeyOpen(true);
  };

  return (
    <Card className="flex h-full flex-col">
      <CardHeader>
        <CardTitle className="text-sm">Decision</CardTitle>
        {!isPending && (
          <Badge variant="secondary" className="w-fit capitalize">
            Already {item.status}
          </Badge>
        )}
      </CardHeader>
      <CardContent className="flex flex-1 flex-col gap-3 overflow-auto">
        {!isPending && (
          <Alert variant="default">
            <AlertDescription>
              This approval is no longer pending. Decision panel disabled.
              {item.decided_at && (
                <div className="mt-1 text-[11px] text-muted-foreground">
                  Decided {new Date(item.decided_at).toLocaleString()} by{" "}
                  {item.decided_by ?? "—"}
                </div>
              )}
            </AlertDescription>
          </Alert>
        )}

        {item.lane === "tier-0-mandatory" && (
          <Alert variant="warning">
            <AlertDescription className="text-xs">
              Tier-0 mandatory review.{" "}
              {item.escalations?.length
                ? `Flags: ${item.escalations.join(", ")}.`
                : "Confidence < 0.70 or policy-flagged."}
            </AlertDescription>
          </Alert>
        )}

        <div className="grid grid-cols-2 gap-2">
          <Button
            variant="success"
            disabled={!isPending || decide.isPending}
            onClick={() => triggerPasskey("approve")}
          >
            <Check className="h-4 w-4" /> Approve
          </Button>
          <Button
            variant="outline"
            disabled={!isPending || decide.isPending}
            onClick={() => setEditOpen(true)}
          >
            <Pencil className="h-4 w-4" /> Edit
          </Button>
          <Button
            variant="destructive"
            disabled={!isPending || decide.isPending}
            onClick={() => setMode("reject")}
          >
            <X className="h-4 w-4" /> Reject
          </Button>
          <Button
            variant="warning"
            disabled={!isPending || decide.isPending}
            onClick={() => setMode("escalate")}
          >
            <ArrowUpFromLine className="h-4 w-4" /> Escalate
          </Button>
        </div>

        {(mode === "reject" || mode === "escalate") && !passkeyOpen && (
          <div className="space-y-1.5">
            <Label htmlFor="reason">
              Reason{" "}
              {mode === "reject" ? (
                <span className="text-destructive">*</span>
              ) : (
                "(optional)"
              )}
            </Label>
            <Textarea
              id="reason"
              rows={4}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder={
                mode === "reject"
                  ? "Why are we rejecting?"
                  : "Why escalate to dual approver?"
              }
            />
            <div className="flex justify-end gap-2">
              <Button variant="ghost" size="sm" onClick={() => setMode(null)}>
                Cancel
              </Button>
              <Button
                size="sm"
                variant={mode === "reject" ? "destructive" : "warning"}
                disabled={mode === "reject" && !reason.trim()}
                onClick={() => setPasskeyOpen(true)}
              >
                Continue → passkey
              </Button>
            </div>
          </div>
        )}
      </CardContent>

      {/* Passkey challenge wraps every decision */}
      {(() => {
        const intent = buildIntent();
        if (!intent) return null;
        const wire = wireDecisionFor(mode)!;
        const verb =
          mode === "approve" || mode === "edit-then-approve"
            ? "Approve"
            : mode === "reject"
              ? "Reject"
              : "Escalate";
        return (
          <PasskeyChallengeModal
            open={passkeyOpen}
            onOpenChange={(v) => {
              setPasskeyOpen(v);
              if (!v) setMode(null);
            }}
            title={`${verb} action`}
            description={
              mode === "approve" || mode === "edit-then-approve"
                ? item.proposed_action.target_system
                  ? `This will execute against ${item.proposed_action.target_system} on confirmation.`
                  : "This will mark the action approved (draft-only, no external write)."
                : `Confirm ${verb.toLowerCase()} for this approval.`
            }
            actionIntent={intent}
            destructive={mode === "reject"}
            onConfirm={async (assertion) => {
              await decide.mutateAsync(
                {
                  id: item.approval_id,
                  decision: wire,
                  reason:
                    wire === "approved" ? undefined : reason || undefined,
                  edited_payload: editedPayload ?? undefined,
                  passkey_assertion: assertion?.auth_assertion,
                },
                {
                  onError: (e) => toast.error(e.message || "Decision failed"),
                },
              );
              finish(verb + "ed");
            }}
          />
        );
      })()}

      <EditPayloadDialog
        open={editOpen}
        onOpenChange={setEditOpen}
        original={item.proposed_action.payload}
        onConfirm={(edited) => {
          setEditedPayload(edited);
          setEditOpen(false);
          triggerPasskey("edit-then-approve");
        }}
      />
    </Card>
  );
}
