import { Plus, RefreshCw, Trash2 } from "lucide-react";
import { useRef, useState } from "react";

import { cameraSnapshotUrl } from "@/api/platform";
import type { Zone, ZoneType } from "@/types/contracts";
import { cn } from "@/lib/cn";
import { ZONE_TYPE_LABEL } from "@/lib/labels";
import { Button } from "@/ui/Button";
import { IconButton } from "@/ui/IconButton";
import { Input } from "@/ui/Input";
import { Select } from "@/ui/Select";
import {
  clampToImage,
  hitTestEdge,
  hitTestVertex,
  isValidPolygon,
  isValidZoneId,
  screenToImage,
  type Point,
} from "./zoneGeometry";

const ZONE_TYPE_OPTIONS = (Object.keys(ZONE_TYPE_LABEL) as ZoneType[]).map((value) => ({
  value,
  label: ZONE_TYPE_LABEL[value],
}));

const VERTEX_HIT_RADIUS = 14;
const EDGE_HIT_RADIUS = 10;

interface Drag {
  zoneId: string;
  vertexIndex: number;
}

export function ZoneEditor({
  cameraId,
  zones: initialZones,
  analysisWidth,
  analysisHeight,
  onSave,
  saving = false,
}: {
  cameraId: string;
  zones: Zone[];
  analysisWidth: number;
  analysisHeight: number;
  onSave: (zones: Zone[]) => void;
  saving?: boolean;
}) {
  const [zones, setZones] = useState<Zone[]>(initialZones);
  const [selectedId, setSelectedId] = useState<string | null>(initialZones[0]?.zone_id ?? null);
  const [drag, setDrag] = useState<Drag | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);
  // The picture is one still frame; a new nonce asks the camera for a fresh one.
  const [snapshotNonce, setSnapshotNonce] = useState(0);
  const [snapshotFailed, setSnapshotFailed] = useState(false);
  const svgRef = useRef<SVGSVGElement | null>(null);
  const imageSize = { width: analysisWidth, height: analysisHeight };

  const selectedZone = zones.find((zone) => zone.zone_id === selectedId) ?? null;

  function updateZone(zoneId: string, patch: Partial<Zone>) {
    setZones((prev) => prev.map((zone) => (zone.zone_id === zoneId ? { ...zone, ...patch } : zone)));
  }

  function toImagePoint(event: { clientX: number; clientY: number }): Point | null {
    const svg = svgRef.current;
    if (!svg) return null;
    const rect = svg.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return null;
    const screenPoint = { x: event.clientX - rect.left, y: event.clientY - rect.top };
    return clampToImage(screenToImage(screenPoint, imageSize, rect), imageSize);
  }

  function handlePointerDown(event: React.PointerEvent<SVGSVGElement>) {
    if (!selectedZone) return;
    const point = toImagePoint(event);
    if (!point) return;

    const vertexIndex = hitTestVertex(point, selectedZone.polygon, VERTEX_HIT_RADIUS);
    if (vertexIndex !== null) {
      setDrag({ zoneId: selectedZone.zone_id, vertexIndex });
      return;
    }

    const polygon = [...selectedZone.polygon];
    if (polygon.length >= 3) {
      const edgeIndex = hitTestEdge(point, polygon, EDGE_HIT_RADIUS);
      if (edgeIndex !== null) {
        polygon.splice(edgeIndex + 1, 0, point);
        updateZone(selectedZone.zone_id, { polygon });
        return;
      }
    }
    polygon.push(point);
    updateZone(selectedZone.zone_id, { polygon });
  }

  function handlePointerMove(event: React.PointerEvent<SVGSVGElement>) {
    if (!drag) return;
    const point = toImagePoint(event);
    if (!point) return;
    const zone = zones.find((z) => z.zone_id === drag.zoneId);
    if (!zone) return;
    const polygon = zone.polygon.map((vertex, index) => (index === drag.vertexIndex ? point : vertex));
    updateZone(drag.zoneId, { polygon });
  }

  function handlePointerUp() {
    setDrag(null);
  }

  function addZone() {
    let base = "zone";
    let id = base;
    let n = 1;
    while (zones.some((z) => z.zone_id === id)) {
      id = `${base}-${n}`;
      n += 1;
    }
    const zone: Zone = { zone_id: id, name: "New zone", zone_type: "QUEUE", polygon: [], width_m: null };
    setZones((prev) => [...prev, zone]);
    setSelectedId(id);
  }

  function deleteZone(zoneId: string) {
    setZones((prev) => prev.filter((zone) => zone.zone_id !== zoneId));
    if (selectedId === zoneId) setSelectedId(null);
  }

  function deleteVertex(zoneId: string, vertexIndex: number) {
    const zone = zones.find((z) => z.zone_id === zoneId);
    if (!zone) return;
    updateZone(zoneId, { polygon: zone.polygon.filter((_, index) => index !== vertexIndex) });
  }

  function handleSave() {
    const invalid = zones.find((zone) => !isValidPolygon(zone.polygon) || !isValidZoneId(zone.zone_id));
    if (invalid) {
      setValidationError(
        !isValidZoneId(invalid.zone_id)
          ? `"${invalid.zone_id}" is not a valid zone id (lowercase letters, numbers, hyphens).`
          : `"${invalid.name}" needs at least 3 points before it can be saved.`,
      );
      return;
    }
    setValidationError(null);
    onSave(zones);
  }

  return (
    <div className="flex flex-col gap-4 lg:flex-row">
      {/* self-start: in a row, a stretched item ignores aspect-ratio and grows to the side panel's
          height - then the picture and the zone overlay are scaled differently and stop lining up. */}
      <div
        className="relative w-full self-start overflow-hidden rounded-md border border-line bg-canvas lg:max-w-2xl"
        style={{ aspectRatio: `${analysisWidth} / ${analysisHeight}` }}
      >
        {/* A clean frame: overlays would hide the edges where zones are drawn. Contained, like the SVG. */}
        {snapshotFailed ? (
          <p className="absolute inset-x-0 top-1/3 px-6 text-center text-xs text-ink-muted">
            No picture from this camera yet. Zones can still be edited by their vertices.
          </p>
        ) : (
          <img
            key={snapshotNonce}
            src={cameraSnapshotUrl(cameraId, [], snapshotNonce)}
            alt="Camera snapshot for zone editing"
            className="absolute inset-0 h-full w-full object-contain"
            onError={() => setSnapshotFailed(true)}
          />
        )}
        <svg
          ref={svgRef}
          viewBox={`0 0 ${analysisWidth} ${analysisHeight}`}
          className="absolute inset-0 h-full w-full touch-none"
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
          onPointerLeave={handlePointerUp}
        >
          {zones.map((zone) => {
            const active = zone.zone_id === selectedId;
            const points = zone.polygon.map((p) => `${p.x},${p.y}`).join(" ");
            return (
              <g key={zone.zone_id} opacity={active ? 1 : 0.55}>
                {zone.polygon.length >= 2 && (
                  <polygon
                    points={points}
                    fill={active ? "rgba(247,249,250,0.12)" : "rgba(247,249,250,0.05)"}
                    stroke={active ? "#F7F9FA" : "#8A96A1"}
                    strokeWidth={2}
                  />
                )}
                {active &&
                  zone.polygon.map((vertex, index) => (
                    <circle
                      key={index}
                      cx={vertex.x}
                      cy={vertex.y}
                      r={7}
                      fill="#0B0E11"
                      stroke="#F7F9FA"
                      strokeWidth={2}
                      onDoubleClick={(event) => {
                        event.stopPropagation();
                        deleteVertex(zone.zone_id, index);
                      }}
                    />
                  ))}
              </g>
            );
          })}
        </svg>
        <p className="pointer-events-none absolute bottom-2 left-2 rounded-xs bg-canvas/80 px-2 py-1 text-2xs text-ink-faint">
          Click to add a point, drag to move, double-click a point to remove it.
        </p>
        <IconButton
          aria-label="Refresh the picture"
          size="sm"
          variant="ghost"
          icon={<RefreshCw size={14} />}
          className="absolute top-2 right-2 bg-canvas/80"
          onClick={() => {
            setSnapshotFailed(false);
            setSnapshotNonce((nonce) => nonce + 1);
          }}
        />
      </div>

      <div className="flex w-full flex-col gap-3 lg:w-80">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-ink-strong">Zones</h3>
          <Button size="sm" variant="secondary" iconStart={<Plus size={14} />} onClick={addZone}>
            New zone
          </Button>
        </div>
        <div className="flex flex-col gap-1">
          {zones.map((zone) => (
            <button
              key={zone.zone_id}
              type="button"
              onClick={() => setSelectedId(zone.zone_id)}
              className={cn(
                "flex items-center justify-between rounded-control border px-2.5 py-1.5 text-left text-sm",
                zone.zone_id === selectedId
                  ? "border-line-strong bg-surface-2 text-ink-strong"
                  : "border-line text-ink-secondary hover:bg-surface-2/60",
              )}
            >
              <span className="truncate">{zone.name || zone.zone_id}</span>
              <span className="text-2xs text-ink-faint">{zone.polygon.length} pts</span>
            </button>
          ))}
          {zones.length === 0 && <p className="text-xs text-ink-faint">No zones yet.</p>}
        </div>

        {selectedZone && (
          <div className="flex flex-col gap-3 rounded-control border border-line bg-surface-2/40 p-3">
            <label className="flex flex-col gap-1 text-xs text-ink-faint">
              Name
              <Input
                value={selectedZone.name}
                onChange={(event) => updateZone(selectedZone.zone_id, { name: event.target.value })}
              />
            </label>
            <label className="flex flex-col gap-1 text-xs text-ink-faint">
              Type
              <Select
                value={selectedZone.zone_type}
                onValueChange={(value) => updateZone(selectedZone.zone_id, { zone_type: value as ZoneType })}
                options={ZONE_TYPE_OPTIONS}
              />
            </label>
            <label className="flex flex-col gap-1 text-xs text-ink-faint">
              Width (metres, optional)
              <Input
                type="number"
                min={0}
                step="0.1"
                value={selectedZone.width_m ?? ""}
                onChange={(event) =>
                  updateZone(selectedZone.zone_id, {
                    width_m: event.target.value === "" ? null : Number(event.target.value),
                  })
                }
              />
            </label>

            {selectedZone.polygon.length > 0 && (
              <div className="flex flex-col gap-1">
                <span className="text-xs text-ink-faint">Vertices</span>
                {selectedZone.polygon.map((vertex, index) => (
                  <div key={index} className="flex items-center gap-1.5">
                    <Input
                      type="number"
                      value={Math.round(vertex.x)}
                      onChange={(event) => {
                        const polygon = selectedZone.polygon.map((p, i) =>
                          i === index ? { ...p, x: Number(event.target.value) } : p,
                        );
                        updateZone(selectedZone.zone_id, { polygon });
                      }}
                      className="h-7 text-xs"
                    />
                    <Input
                      type="number"
                      value={Math.round(vertex.y)}
                      onChange={(event) => {
                        const polygon = selectedZone.polygon.map((p, i) =>
                          i === index ? { ...p, y: Number(event.target.value) } : p,
                        );
                        updateZone(selectedZone.zone_id, { polygon });
                      }}
                      className="h-7 text-xs"
                    />
                    <IconButton
                      aria-label="Delete vertex"
                      size="sm"
                      variant="ghost"
                      icon={<Trash2 size={13} />}
                      onClick={() => deleteVertex(selectedZone.zone_id, index)}
                    />
                  </div>
                ))}
              </div>
            )}

            <Button variant="danger" size="sm" onClick={() => deleteZone(selectedZone.zone_id)}>
              Delete zone
            </Button>
          </div>
        )}

        {validationError && <p className="text-xs text-critical-text">{validationError}</p>}
        <Button variant="primary" loading={saving} onClick={handleSave}>
          Save zones
        </Button>
      </div>
    </div>
  );
}

