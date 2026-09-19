import { useState } from "react";

import { LayerToggle } from "@/components/video/LayerToggle";
import { LiveStream } from "@/components/video/LiveStream";
import { CountMethodTag } from "@/components/status/CountMethodTag";
import { StaleBadge } from "@/components/status/StaleBadge";
import { StatusPill } from "@/components/status/StatusPill";
import { StateStrip } from "@/components/status/StateStrip";
import { Panel } from "@/components/data/Panel";
import { PageHeader } from "@/features/shell/PageHeader";
import { formatCsi, formatInteger } from "@/lib/format";
import { useCameraFigures } from "@/realtime/cameraFigures";
import { useLive } from "@/realtime/store";
import type { StreamLayer } from "@/types/contracts";
import { CsiInstrument } from "./CsiInstrument";
import { EvidencePanel } from "./EvidencePanel";
import { FocusCameraSwitcher } from "./FocusCameraSwitcher";
import { GuidancePanel } from "./GuidancePanel";
import { LiveTimeline } from "./LiveTimeline";
import { QueueStrip } from "./QueueStrip";
import { SessionTrends } from "./SessionTrends";
import { SiteSummary } from "./SiteSummary";
import { useFocusCamera } from "./useFocusCamera";

const DEFAULT_LAYERS: StreamLayer[] = ["hud", "tracks", "zones"];

export function CommandCenterPage() {
  const [focusCameraId, setFocusCamera] = useFocusCamera();
  const [layers, setLayers] = useState<StreamLayer[]>(DEFAULT_LAYERS);

  const camera = useLive((state) => (focusCameraId ? state.cameras[focusCameraId] : undefined));
  const { analysis, withheldReason, staleSeconds } = useCameraFigures(focusCameraId);
  const decision = useLive((state) => (focusCameraId ? state.decisions[focusCameraId] : undefined));
  const site = useLive((state) => state.site);

  const status = analysis?.stability.status ?? null;
  const csi = analysis?.stability.csi_smoothed ?? null;
  const state = decision?.operational_state ?? "MONITORING";

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Command Center"
        description={camera ? [camera.name, camera.location].filter(Boolean).join(", ") : "Waiting for a camera feed."}
      />

      <Panel bodyClassName="p-3 sm:p-4">
        <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
          <StatusPill status={status} />
          <span className="readout text-sm text-ink-secondary">
            CSI <span className="text-ink-strong">{formatCsi(csi)}</span>
          </span>
          {staleSeconds !== null && <StaleBadge isStale ageSeconds={staleSeconds} />}
          <StateStrip state={state} />
          <span className="text-sm text-ink-secondary">
            {analysis ? (
              <>
                <span className="readout text-ink-strong">{formatInteger(analysis.crowd.person_count)}</span> people{" "}
                <CountMethodTag method={analysis.crowd.count_method} className="ml-1" />
              </>
            ) : withheldReason ? (
              "No people count"
            ) : (
              "No people count yet"
            )}
          </span>
          {site && (
            <span className="text-sm text-ink-muted">
              {site.cameras_contributing}/{site.cameras_total} cameras contributing
            </span>
          )}
        </div>
        {withheldReason && (
          <p className="mt-3 border-t border-line pt-3 text-sm text-ink-secondary">{withheldReason}</p>
        )}
      </Panel>

      <FocusCameraSwitcher focusCameraId={focusCameraId} onSelect={setFocusCamera} />

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-12">
        <div className="flex flex-col gap-5 xl:col-span-8">
          <Panel
            title={camera?.name ?? "Camera"}
            meta={camera?.status_detail ?? undefined}
            actions={<LayerToggle value={layers} onChange={setLayers} />}
            state={focusCameraId ? "ready" : "waiting"}
            stateMessage="No cameras are configured yet."
          >
            {focusCameraId && (
              <LiveStream
                cameraId={focusCameraId}
                layers={layers}
                running
                statusDetail={camera?.status_detail}
              />
            )}
          </Panel>

          <CsiInstrument
            assessment={analysis?.stability ?? null}
            withheldReason={withheldReason}
            staleSeconds={staleSeconds}
          />
          {focusCameraId && <GuidancePanel cameraId={focusCameraId} decision={decision} />}
          <EvidencePanel
            evidence={analysis?.evidence ?? null}
            withheldReason={withheldReason}
            staleSeconds={staleSeconds}
          />
          <QueueStrip analysis={analysis} withheldReason={withheldReason} staleSeconds={staleSeconds} />
        </div>

        <div className="flex flex-col gap-5 xl:col-span-4">
          <SiteSummary />
          <SessionTrends cameraId={focusCameraId} withheld={withheldReason !== null} />
          <LiveTimeline />
        </div>
      </div>
    </div>
  );
}
