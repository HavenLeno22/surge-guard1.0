import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";

import { camerasApi } from "@/api/platform";
import { isApiError } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { OperationalState, OperationalStatus, OperatorAction } from "@/types/contracts";
import { Button } from "@/ui/Button";
import { Dialog } from "@/ui/Dialog";
import { Textarea } from "@/ui/Textarea";

function allowed(state: OperationalState, status: OperationalStatus | null): Record<OperatorAction, boolean> {
  return {
    ACKNOWLEDGE: state === "OBSERVING",
    LOG_ACTION: state === "OBSERVING" || state === "INVESTIGATING",
    CLOSE: status === "STABLE" && state !== "MONITORING",
  };
}

export function OperatorActions({
  cameraId,
  state,
  status,
  topRuleId,
}: {
  cameraId: string;
  state: OperationalState;
  status: OperationalStatus | null;
  /** The current top recommendation's rule id, attached to a logged action for traceability. */
  topRuleId?: string | null;
}) {
  const queryClient = useQueryClient();
  const [noteOpen, setNoteOpen] = useState(false);
  const [note, setNote] = useState("");
  const can = allowed(state, status);

  const mutation = useMutation({
    mutationFn: (variables: { action: OperatorAction; note?: string }) =>
      camerasApi.operate(cameraId, variables.action, variables.note, topRuleId ?? undefined),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.decisionHistory });
    },
    onError: (error) => {
      toast.error(
        isApiError(error) && error.isConflict
          ? error.message
          : "The action could not be recorded. Try again.",
      );
    },
  });

  function act(action: OperatorAction, actionNote?: string) {
    mutation.mutate({ action, note: actionNote });
  }

  return (
    <div className="flex flex-wrap gap-2">
      <Button
        size="sm"
        variant="secondary"
        disabled={!can.ACKNOWLEDGE || mutation.isPending}
        onClick={() => act("ACKNOWLEDGE")}
      >
        Acknowledge
      </Button>
      <Button
        size="sm"
        variant="secondary"
        disabled={!can.LOG_ACTION || mutation.isPending}
        onClick={() => setNoteOpen(true)}
      >
        Log action
      </Button>
      <Button
        size="sm"
        variant="primary"
        disabled={!can.CLOSE || mutation.isPending}
        onClick={() => act("CLOSE")}
      >
        Close
      </Button>

      <Dialog
        open={noteOpen}
        onOpenChange={setNoteOpen}
        title="Log action"
        description="Record what was done. This note joins the timeline."
        footer={
          <>
            <Button variant="secondary" onClick={() => setNoteOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="primary"
              loading={mutation.isPending}
              onClick={() => {
                act("LOG_ACTION", note.trim() || undefined);
                setNoteOpen(false);
                setNote("");
              }}
            >
              Log action
            </Button>
          </>
        }
      >
        <Textarea
          value={note}
          onChange={(event) => setNote(event.target.value)}
          placeholder="What action was taken? (optional)"
          maxLength={500}
        />
      </Dialog>
    </div>
  );
}
