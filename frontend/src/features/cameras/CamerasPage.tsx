import { Plus } from "lucide-react";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { camerasApi } from "@/api/platform";
import { queryKeys } from "@/api/queryKeys";
import { isApiError } from "@/api/client";
import { Panel } from "@/components/data/Panel";
import { useIsAdmin } from "@/features/auth/useIsAdmin";
import { PageHeader } from "@/features/shell/PageHeader";
import { Button } from "@/ui/Button";
import { CameraFormDrawer } from "./CameraFormDrawer";
import { CameraTile } from "./CameraTile";

export function CamerasPage() {
  const isAdmin = useIsAdmin();
  const [addOpen, setAddOpen] = useState(false);
  const { data, isPending, isError, error, refetch } = useQuery({
    queryKey: queryKeys.cameras,
    queryFn: ({ signal }) => camerasApi.list(signal),
    refetchInterval: 15_000,
  });

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Cameras"
        description={data ? `${data.contributing} of ${data.total} cameras contributing, ${data.enabled} enabled` : undefined}
        actions={
          isAdmin && (
            <Button variant="primary" iconStart={<Plus size={15} />} onClick={() => setAddOpen(true)}>
              Add camera
            </Button>
          )
        }
      />

      {data?.registry_error && (
        <div className="rounded-control border border-attention/30 bg-attention/8 px-4 py-3 text-sm text-attention">
          {data.registry_error}
        </div>
      )}

      <Panel
        state={isPending ? "loading" : isError ? "error" : data && data.cameras.length === 0 ? "empty" : "ready"}
        stateMessage={
          isError
            ? isApiError(error)
              ? error.message
              : "Could not load cameras."
            : "No cameras are configured yet."
        }
        onRetry={() => refetch()}
      >
        {data && data.cameras.length > 0 && (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {data.cameras.map((camera) => (
              <CameraTile key={camera.camera_id} camera={camera} />
            ))}
          </div>
        )}
      </Panel>

      <CameraFormDrawer open={addOpen} onOpenChange={setAddOpen} />
    </div>
  );
}
