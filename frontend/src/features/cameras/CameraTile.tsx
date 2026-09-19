import { Link } from "react-router";

import { CameraStatus } from "@/components/status/CameraStatus";
import { SnapshotImage } from "@/components/video/SnapshotImage";
import { SourceModeBadge } from "@/features/shell/SourceModeBadge";
import { formatInteger } from "@/lib/format";
import type { Camera } from "@/types/contracts";

export function CameraTile({ camera }: { camera: Camera }) {
  return (
    <Link
      to={`/cameras/${encodeURIComponent(camera.camera_id)}`}
      className="group flex flex-col overflow-hidden rounded-md border border-line bg-surface-1 transition-colors duration-120 ease-out-soft hover:border-line-strong"
    >
      <SnapshotImage
        cameraId={camera.camera_id}
        layers={["hud"]}
        active={camera.status !== "OFFLINE" && camera.status !== "DISABLED"}
        alt={`Snapshot: ${camera.name}`}
      />
      <div className="flex flex-col gap-2 p-3">
        <div className="flex items-center justify-between gap-2">
          <span className="truncate text-sm font-medium text-ink-strong">{camera.name}</span>
          {camera.is_primary && <span className="text-2xs text-ink-faint">Primary</span>}
        </div>
        <div className="flex items-center justify-between gap-2">
          <CameraStatus status={camera.status} />
          <SourceModeBadge mode={camera.source_mode} />
        </div>
        <div className="flex items-center justify-between text-2xs text-ink-faint">
          <span>{camera.location || camera.coverage_area}</span>
          <span>
            {camera.metrics.people_count === null ? "—" : formatInteger(camera.metrics.people_count)} people
          </span>
        </div>
      </div>
    </Link>
  );
}
