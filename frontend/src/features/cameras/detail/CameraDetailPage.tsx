import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router";
import { toast } from "sonner";

import { camerasApi } from "@/api/platform";
import { isApiError } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import { LayerToggle } from "@/components/video/LayerToggle";
import { LiveStream } from "@/components/video/LiveStream";
import { CameraStatus } from "@/components/status/CameraStatus";
import { StaleBadge } from "@/components/status/StaleBadge";
import { Panel } from "@/components/data/Panel";
import { QueueStrip } from "@/features/command-center/QueueStrip";
import { useIsAdmin } from "@/features/auth/useIsAdmin";
import { PageHeader } from "@/features/shell/PageHeader";
import { useCameraFigures } from "@/realtime/cameraFigures";
import { useLive } from "@/realtime/store";
import type { StreamLayer, Zone } from "@/types/contracts";
import { Button } from "@/ui/Button";
import { Dialog } from "@/ui/Dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/ui/Tabs";
import { CameraAnalysisPanel } from "./CameraAnalysis";
import { CountersEditor } from "./CountersEditor";
import { DeviceMetrics } from "./DeviceMetrics";
import { ZoneEditor } from "./ZoneEditor";
import { ZoneFlowTable } from "./ZoneFlowTable";
import { CameraFormDrawer } from "../CameraFormDrawer";

export function CameraDetailPage() {
  const { cameraId = "" } = useParams<{ cameraId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const isAdmin = useIsAdmin();

  const [layers, setLayers] = useState<StreamLayer[]>(["hud", "tracks", "zones"]);
  const [editOpen, setEditOpen] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const camera = useLive((state) => state.cameras[cameraId]);
  const { analysis, withheldReason, staleSeconds } = useCameraFigures(cameraId);
  const staleMeta = staleSeconds !== null ? <StaleBadge isStale ageSeconds={staleSeconds} /> : undefined;

  const zonesQuery = useQuery({
    queryKey: queryKeys.cameraZones(cameraId),
    queryFn: ({ signal }) => camerasApi.zones(cameraId, signal),
    enabled: Boolean(cameraId),
  });
  const countersQuery = useQuery({
    queryKey: queryKeys.cameraCounters(cameraId),
    queryFn: ({ signal }) => camerasApi.counters(cameraId, signal),
    enabled: Boolean(cameraId),
  });

  const retryMutation = useMutation({
    mutationFn: () => camerasApi.retry(cameraId),
    onError: (error) => toast.error(isApiError(error) ? error.message : "Retry failed."),
  });
  const testMutation = useMutation({
    mutationFn: () => camerasApi.testCamera(cameraId),
    onSuccess: (result) => toast(result.success ? "Connection succeeded." : `Connection failed: ${result.detail}`),
    onError: (error) => toast.error(isApiError(error) ? error.message : "Test failed."),
  });
  const toggleMutation = useMutation({
    mutationFn: () => camerasApi.update(cameraId, { enabled: !camera?.enabled }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: queryKeys.cameras }),
    onError: (error) => toast.error(isApiError(error) ? error.message : "Could not change enabled state."),
  });
  const deleteMutation = useMutation({
    mutationFn: () => camerasApi.remove(cameraId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.cameras });
      navigate("/cameras");
    },
    onError: (error) => toast.error(isApiError(error) ? error.message : "Could not delete the camera."),
  });
  const saveZonesMutation = useMutation({
    mutationFn: (zones: Zone[]) => camerasApi.saveZones(cameraId, zones),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.cameraZones(cameraId) });
      toast.success("Zones saved.");
    },
    onError: (error) => toast.error(isApiError(error) ? error.message : "Could not save zones."),
  });

  const analysisWidth = camera?.metrics.analysis_width ?? 960;
  const analysisHeight = camera?.metrics.analysis_height ?? 540;

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title={camera?.name ?? cameraId}
        description={camera ? [camera.location, camera.coverage_area].filter(Boolean).join(", ") || undefined : undefined}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Button asChild variant="ghost" size="sm">
              <Link to="/cameras">All cameras</Link>
            </Button>
            <Button size="sm" variant="secondary" loading={testMutation.isPending} onClick={() => testMutation.mutate()}>
              Test connection
            </Button>
            <Button size="sm" variant="secondary" loading={retryMutation.isPending} onClick={() => retryMutation.mutate()}>
              Retry
            </Button>
            {isAdmin && (
              <>
                <Button size="sm" variant="secondary" onClick={() => setEditOpen(true)}>
                  Edit
                </Button>
                <Button size="sm" variant="secondary" loading={toggleMutation.isPending} onClick={() => toggleMutation.mutate()}>
                  {camera?.enabled ? "Disable" : "Enable"}
                </Button>
                {/* Quiet in the toolbar; the confirmation dialog carries the filled destructive button. */}
                <Button
                  size="sm"
                  variant="ghost"
                  className="text-critical-text hover:bg-critical/10 hover:text-critical-text"
                  onClick={() => setConfirmDelete(true)}
                >
                  Delete
                </Button>
              </>
            )}
          </div>
        }
      />

      {camera && (
        <div className="flex items-center gap-3">
          <CameraStatus status={camera.status} />
          {camera.status_detail && <span className="text-xs text-ink-faint">{camera.status_detail}</span>}
        </div>
      )}

      <Tabs defaultValue="overview">
        <TabsList>
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="zones">Zones</TabsTrigger>
          <TabsTrigger value="counters">Counters</TabsTrigger>
        </TabsList>

        <TabsContent value="overview" className="mt-4 flex flex-col gap-5">
          <Panel
            title="Live stream"
            actions={<LayerToggle value={layers} onChange={setLayers} />}
            state={cameraId ? "ready" : "waiting"}
          >
            <LiveStream cameraId={cameraId} layers={layers} running statusDetail={camera?.status_detail} />
          </Panel>

          <Panel title="Device and pipeline" state={camera ? "ready" : "waiting"}>
            {camera && <DeviceMetrics metrics={camera.metrics} />}
          </Panel>

          <Panel
            title="Analysis"
            meta={staleMeta}
            state={withheldReason ? "empty" : !analysis ? "waiting" : staleSeconds !== null ? "stale" : "ready"}
            stateMessage={withheldReason ?? "No analysis for this camera yet."}
          >
            {analysis && <CameraAnalysisPanel analysis={analysis} />}
          </Panel>

          <Panel
            title="Zone flow"
            meta={staleMeta}
            state={analysis?.zone_flow ? (staleSeconds !== null ? "stale" : "ready") : "empty"}
            stateMessage={withheldReason ?? "Zone flow appears once this camera has zones to count movement between."}
          >
            <ZoneFlowTable report={analysis?.zone_flow} />
          </Panel>

          <QueueStrip analysis={analysis} withheldReason={withheldReason} staleSeconds={staleSeconds} />
        </TabsContent>

        <TabsContent value="zones" className="mt-4">
          <Panel
            title="Zone editor"
            state={zonesQuery.isPending ? "loading" : zonesQuery.isError ? "error" : "ready"}
            onRetry={() => zonesQuery.refetch()}
          >
            {zonesQuery.data && (
              <>
                {zonesQuery.data.requires_restart && (
                  <p className="mb-3 text-xs text-attention">
                    Saved zones take effect after this camera's pipeline restarts.
                  </p>
                )}
                <ZoneEditor
                  cameraId={cameraId}
                  zones={zonesQuery.data.zones}
                  analysisWidth={analysisWidth}
                  analysisHeight={analysisHeight}
                  saving={saveZonesMutation.isPending}
                  onSave={(zones) => saveZonesMutation.mutate(zones)}
                />
              </>
            )}
          </Panel>
        </TabsContent>

        <TabsContent value="counters" className="mt-4">
          <Panel
            title="Counters"
            state={countersQuery.isPending ? "loading" : countersQuery.isError ? "error" : "ready"}
            onRetry={() => countersQuery.refetch()}
          >
            {countersQuery.data && <CountersEditor cameraId={cameraId} counters={countersQuery.data.counters} />}
          </Panel>
        </TabsContent>
      </Tabs>

      {camera && <CameraFormDrawer open={editOpen} onOpenChange={setEditOpen} camera={camera} />}

      <Dialog
        open={confirmDelete}
        onOpenChange={setConfirmDelete}
        title="Delete this camera?"
        description={`${camera?.name ?? cameraId} will stop contributing to the site. This cannot be undone.`}
        footer={
          <>
            <Button variant="secondary" onClick={() => setConfirmDelete(false)}>
              Cancel
            </Button>
            <Button
              variant="danger"
              loading={deleteMutation.isPending}
              onClick={() => {
                deleteMutation.mutate();
                setConfirmDelete(false);
              }}
            >
              Delete
            </Button>
          </>
        }
      />
    </div>
  );
}
