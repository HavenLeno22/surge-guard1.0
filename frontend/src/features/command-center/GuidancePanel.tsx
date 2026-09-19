import { CausesList } from "@/components/intel/CausesList";
import { ActionList } from "@/components/intel/ActionList";
import { Panel } from "@/components/data/Panel";
import { StaleBadge } from "@/components/status/StaleBadge";
import type { CameraDecision } from "@/types/contracts";
import { OperatorActions } from "./OperatorActions";

export function GuidancePanel({ cameraId, decision }: { cameraId: string; decision: CameraDecision | undefined }) {
  const report = decision?.report ?? null;

  return (
    <Panel
      title="Operational guidance"
      meta={decision && <StaleBadge isStale={decision.is_stale} ageSeconds={decision.age_seconds} />}
      actions={
        decision && (
          <OperatorActions
            cameraId={cameraId}
            state={decision.operational_state}
            status={report?.status ?? null}
            topRuleId={report?.recommended_actions[0]?.rule_id}
          />
        )
      }
      state={!decision ? "waiting" : !report ? "empty" : "ready"}
      stateMessage={!report ? "No guidance has been generated for this camera yet." : undefined}
    >
      {report && (
        <div className="flex flex-col gap-5">
          <p className="text-sm text-ink">{report.situation_summary}</p>
          {report.dominant_contributor_statement && (
            <p className="text-xs text-ink-muted">{report.dominant_contributor_statement}</p>
          )}
          <div className="grid gap-5 sm:grid-cols-2">
            <div>
              <h3 className="mb-2 text-xs font-medium text-ink-faint">Primary causes</h3>
              <CausesList causes={report.primary_causes} />
            </div>
            <div>
              <h3 className="mb-2 text-xs font-medium text-ink-faint">Recommended actions</h3>
              <ActionList actions={report.recommended_actions} />
            </div>
          </div>
        </div>
      )}
    </Panel>
  );
}
