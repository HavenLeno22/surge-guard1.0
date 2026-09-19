import { formatCsi } from "@/lib/format";
import { STATUS_LABEL } from "@/lib/labels";
import { TONE_HEX } from "@/lib/status";
import { statusFromCsi } from "@/lib/status";

const CX = 100;
const CY = 104;
const RADIUS = 84;
const STROKE = 14;

const SEGMENTS: { from: number; to: number; hex: string }[] = [
  { from: 0, to: 20, hex: TONE_HEX.critical },
  { from: 20, to: 40, hex: TONE_HEX.high },
  { from: 40, to: 60, hex: TONE_HEX.attention },
  { from: 60, to: 80, hex: TONE_HEX.observe },
  { from: 80, to: 100, hex: TONE_HEX.stable },
];

function angleFor(value: number): number {
  return 180 - (Math.min(Math.max(value, 0), 100) / 100) * 180;
}

function polarPoint(angleDeg: number, radius: number): { x: number; y: number } {
  const radians = (angleDeg * Math.PI) / 180;
  return { x: CX + radius * Math.cos(radians), y: CY - radius * Math.sin(radians) };
}

function arcPath(fromValue: number, toValue: number, radius: number): string {
  const start = polarPoint(angleFor(fromValue), radius);
  const end = polarPoint(angleFor(toValue), radius);
  return `M ${start.x} ${start.y} A ${radius} ${radius} 0 0 1 ${end.x} ${end.y}`;
}

/** The CSI band as an instrument: the product's signature motif, radial form. */
export function CsiGauge({ value, size = 176 }: { value: number | null; size?: number }) {
  const status = value === null ? null : statusFromCsi(value);
  // A marker across the band rather than a needle from the centre: the centre holds the readout,
  // and a needle would cross the number whenever the index sits near either end of the scale.
  const marker =
    value === null
      ? null
      : {
          inner: polarPoint(angleFor(value), RADIUS - STROKE / 2 - 7),
          outer: polarPoint(angleFor(value), RADIUS + STROKE / 2 + 4),
        };

  return (
    <div className="flex flex-col items-center" style={{ width: size }}>
      <svg viewBox="-6 -6 212 124" width={size} height={(size * 124) / 212}>
        <title>
          {value === null
            ? "Crowd Stability Index unavailable"
            : `Crowd Stability Index ${formatCsi(value)}, ${STATUS_LABEL[status!]}`}
        </title>
        {SEGMENTS.map((segment) => (
          <path
            key={segment.from}
            d={arcPath(segment.from, segment.to, RADIUS)}
            fill="none"
            stroke={segment.hex}
            strokeWidth={STROKE}
            strokeLinecap="butt"
            opacity={value === null ? 0.28 : 1}
          />
        ))}
        {marker && (
          <>
            <line
              x1={marker.inner.x}
              y1={marker.inner.y}
              x2={marker.outer.x}
              y2={marker.outer.y}
              stroke="var(--color-canvas)"
              strokeWidth={7}
              strokeLinecap="round"
            />
            <line
              x1={marker.inner.x}
              y1={marker.inner.y}
              x2={marker.outer.x}
              y2={marker.outer.y}
              stroke="var(--color-ink-strong)"
              strokeWidth={3}
              strokeLinecap="round"
            />
          </>
        )}
      </svg>
      <div className="-mt-9 flex flex-col items-center">
        <span className="readout text-4xl text-ink-strong">{formatCsi(value)}</span>
        <span className="text-xs text-ink-muted">{status ? STATUS_LABEL[status] : "No data"}</span>
      </div>
    </div>
  );
}
