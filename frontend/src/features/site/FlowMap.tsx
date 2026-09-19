import { EmptyState } from "@/components/data/EmptyState";
import type { SiteFlowNode, ZoneFlowLink } from "@/types/contracts";

const COL_WIDTH = 180;
const ROW_HEIGHT = 52;

/** Zones grouped by camera in columns; links TRACKED (solid) versus CORRELATED (dashed). */
export function FlowMap({ nodes, links }: { nodes: SiteFlowNode[]; links: ZoneFlowLink[] }) {
  if (nodes.length === 0) {
    return <EmptyState title="No flow data yet" description="Flow appears once cameras have zones and traffic between them." />;
  }

  const cameraIds = Array.from(new Set(nodes.map((node) => node.camera_id)));
  const positions = new Map<string, { x: number; y: number }>();
  let maxRows = 1;
  cameraIds.forEach((cameraId, colIndex) => {
    const zonesForCamera = nodes.filter((node) => node.camera_id === cameraId);
    maxRows = Math.max(maxRows, zonesForCamera.length);
    zonesForCamera.forEach((node, rowIndex) => {
      positions.set(node.node_id, { x: colIndex * COL_WIDTH + COL_WIDTH / 2, y: rowIndex * ROW_HEIGHT + 44 });
    });
  });

  const width = Math.max(COL_WIDTH * cameraIds.length, 240);
  const height = maxRows * ROW_HEIGHT + 32;

  return (
    <div className="overflow-x-auto">
      <svg width={width} height={height} className="min-w-full">
        <title>Site flow map</title>
        {cameraIds.map((cameraId, colIndex) => (
          <text
            key={cameraId}
            x={colIndex * COL_WIDTH + COL_WIDTH / 2}
            y={16}
            textAnchor="middle"
            className="fill-ink-faint text-[10px]"
          >
            {nodes.find((node) => node.camera_id === cameraId)?.camera_name ?? cameraId}
          </text>
        ))}
        {links.map((link) => {
          const from = positions.get(link.from_node_id);
          const to = positions.get(link.to_node_id);
          if (!from || !to) return null;
          const color = link.basis === "TRACKED" ? "#F7F9FA" : link.basis === "CORRELATED" ? "#8A96A1" : "#5D6A76";
          return (
            <line
              key={link.link_id}
              x1={from.x}
              y1={from.y}
              x2={to.x}
              y2={to.y}
              stroke={color}
              strokeWidth={1.5}
              strokeDasharray={link.basis === "TRACKED" ? undefined : "4 3"}
            >
              <title>{link.explanation}</title>
            </line>
          );
        })}
        {nodes.map((node) => {
          const pos = positions.get(node.node_id);
          if (!pos) return null;
          return (
            <g key={node.node_id} opacity={node.available ? 1 : 0.45}>
              <rect
                x={pos.x - 60}
                y={pos.y - 14}
                width={120}
                height={28}
                rx={5}
                className="fill-surface-2 stroke-line-strong"
              />
              <text x={pos.x} y={pos.y + 4} textAnchor="middle" className="fill-ink text-[10px]">
                {node.zone_name}
              </text>
            </g>
          );
        })}
      </svg>
      <div className="mt-2 flex gap-4 text-2xs text-ink-faint">
        <span className="inline-flex items-center gap-1.5">
          <span className="h-px w-4 bg-ink-strong" /> Tracked
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="h-px w-4 border-t border-dashed border-ink-muted" /> Correlated
        </span>
      </div>
    </div>
  );
}
