import { useEffect, useRef, useState } from "react";

import { BandScale } from "@/components/brand/BandScale";
import { cn } from "@/lib/cn";
import { formatCsi } from "@/lib/format";
import { INDICATOR_DEFAULT_WEIGHT } from "@/lib/labels";
import { statusFromCsi, STATUS_TONE, TONE_HEX } from "@/lib/status";
import {
  createRng,
  createVenue,
  indicatorPressures,
  NECK,
  step,
  stabilityIndex,
  VENUE_HEIGHT,
  VENUE_WIDTH,
  type VenueState,
} from "./venueSim";

const INK_STRONG = "#F7F9FA";
const INK_MUTED = "#8A96A1";
const LINE = "#242C34";
const LINE_STRONG = "#33404B";
const SURFACE_2 = "#171D23";

function draw(ctx: CanvasRenderingContext2D, state: VenueState, pressure: number): void {
  ctx.clearRect(0, 0, VENUE_WIDTH, VENUE_HEIGHT);

  // Schematic zones: entry, concourse, queue neck, exit.
  ctx.strokeStyle = LINE;
  ctx.lineWidth = 1;
  ctx.setLineDash([4, 6]);
  ctx.strokeRect(8, 8, VENUE_WIDTH - 16, VENUE_HEIGHT - 16);
  ctx.beginPath();
  ctx.moveTo(NECK.xFrom, 8);
  ctx.lineTo(NECK.xFrom, VENUE_HEIGHT - 8);
  ctx.moveTo(NECK.xTo, 8);
  ctx.lineTo(NECK.xTo, VENUE_HEIGHT - 8);
  ctx.stroke();
  ctx.setLineDash([]);

  ctx.fillStyle = LINE_STRONG;
  ctx.fillRect(NECK.xFrom, 8, NECK.xTo - NECK.xFrom, NECK.yFrom - 8);
  ctx.fillRect(NECK.xFrom, NECK.yTo, NECK.xTo - NECK.xFrom, VENUE_HEIGHT - 8 - NECK.yTo);

  ctx.font = "11px ui-sans-serif, system-ui";
  ctx.fillStyle = INK_MUTED;
  ctx.fillText("Entry", 16, 24);
  ctx.fillText("Concourse", 220, 24);
  ctx.fillText("Queue lane", NECK.xFrom - 4, NECK.yFrom - 10);
  ctx.fillText("Exit", VENUE_WIDTH - 40, 24);

  // Density bloom at the neck, intensity from the same pressure the HUD reads.
  if (pressure > 8) {
    const cx = (NECK.xFrom + NECK.xTo) / 2;
    const cy = (NECK.yFrom + NECK.yTo) / 2;
    const radius = 40 + pressure * 0.9;
    const gradient = ctx.createRadialGradient(cx, cy, 4, cx, cy, radius);
    const tone = TONE_HEX[STATUS_TONE[statusFromCsi(100 - pressure)]];
    gradient.addColorStop(0, `${tone}33`);
    gradient.addColorStop(1, `${tone}00`);
    ctx.fillStyle = gradient;
    ctx.beginPath();
    ctx.arc(cx, cy, radius, 0, Math.PI * 2);
    ctx.fill();
  }

  // Agents, with a velocity trail and a couple of tracking brackets.
  state.agents.forEach((agent, index) => {
    ctx.strokeStyle = `${INK_MUTED}66`;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(agent.x, agent.y);
    ctx.lineTo(agent.x - agent.vx * 0.35, agent.y - agent.vy * 0.35);
    ctx.stroke();

    ctx.fillStyle = SURFACE_2;
    ctx.strokeStyle = INK_STRONG;
    ctx.lineWidth = 1.25;
    ctx.beginPath();
    ctx.arc(agent.x, agent.y, 3.2, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();

    if (index % 7 === 0) {
      const size = 9;
      ctx.strokeStyle = `${INK_STRONG}99`;
      ctx.lineWidth = 1;
      const { x, y } = agent;
      ctx.beginPath();
      ctx.moveTo(x - size, y - size + 3);
      ctx.lineTo(x - size, y - size);
      ctx.lineTo(x - size + 3, y - size);
      ctx.moveTo(x + size, y - size + 3);
      ctx.lineTo(x + size, y - size);
      ctx.lineTo(x + size - 3, y - size);
      ctx.moveTo(x - size, y + size - 3);
      ctx.lineTo(x - size, y + size);
      ctx.lineTo(x - size + 3, y + size);
      ctx.moveTo(x + size, y + size - 3);
      ctx.lineTo(x + size, y + size);
      ctx.lineTo(x + size - 3, y + size);
      ctx.stroke();
    }
  });
}

/**
 * The hero's canvas instrument: a schematic venue, not a camera feed. Pauses
 * off-screen and on a hidden tab, and freezes to one representative frame
 * under `prefers-reduced-motion`.
 */
export function VenueCanvas({ className }: { className?: string }) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [csi, setCsi] = useState(100);

  useEffect(() => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !container || !ctx) return;

    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = VENUE_WIDTH * dpr;
    canvas.height = VENUE_HEIGHT * dpr;
    ctx.scale(dpr, dpr);

    // Twenty simulated seconds before the first frame, so the venue is already
    // in motion when the page opens rather than filling up from an empty room.
    let venueState = createVenue(42);
    const warmupRng = createRng(99);
    for (let i = 0; i < 600; i += 1) venueState = step(venueState, 1 / 30, warmupRng);
    const warm = indicatorPressures(venueState);
    let smoothedCsi = stabilityIndex(warm.pressures, INDICATOR_DEFAULT_WEIGHT, warm.available);
    let visible = true;
    let running = true;
    let rafId = 0;
    let lastTime = performance.now();

    function renderFrame(state: VenueState, csiValue: number) {
      if (!ctx) return;
      const { pressures, available } = indicatorPressures(state);
      const pressure = 100 - stabilityIndex(pressures, INDICATOR_DEFAULT_WEIGHT, available);
      draw(ctx, state, pressure);
      setCsi(csiValue);
    }

    if (reducedMotion) {
      renderFrame(venueState, smoothedCsi);
    } else {
      const tick = (now: number) => {
        if (!running) return;
        const dt = Math.min((now - lastTime) / 1000, 0.1);
        lastTime = now;
        if (visible) {
          venueState = step(venueState, dt);
          const { pressures, available } = indicatorPressures(venueState);
          const raw = stabilityIndex(pressures, INDICATOR_DEFAULT_WEIGHT, available);
          const alpha = 1 - Math.exp(-dt / 10);
          smoothedCsi = smoothedCsi + (raw - smoothedCsi) * alpha;
          renderFrame(venueState, smoothedCsi);
        }
        rafId = requestAnimationFrame(tick);
      };
      rafId = requestAnimationFrame(tick);
    }

    const observer = new IntersectionObserver(
      ([entry]) => {
        visible = entry?.isIntersecting ?? true;
      },
      { threshold: 0.1 },
    );
    observer.observe(container);

    return () => {
      running = false;
      cancelAnimationFrame(rafId);
      observer.disconnect();
    };
  }, []);

  return (
    <div
      ref={containerRef}
      className={cn("relative overflow-hidden rounded-lg border border-line bg-surface-1", className)}
    >
      {/* Decorative: the caption and the CSI readout below say what it shows. */}
      <canvas ref={canvasRef} aria-hidden="true" className="block w-full" style={{ aspectRatio: `${VENUE_WIDTH} / ${VENUE_HEIGHT}` }} />
      <div className="pointer-events-none absolute inset-x-0 bottom-0 flex flex-col gap-2 bg-gradient-to-t from-canvas via-canvas/80 to-transparent px-4 pt-8 pb-4">
        <div className="flex items-center justify-between">
          <span className="text-2xs text-ink-faint">Illustrative simulation, not live data</span>
          <span className="readout text-sm text-ink-strong">CSI {formatCsi(csi)}</span>
        </div>
        <BandScale value={csi} size="sm" />
      </div>
    </div>
  );
}
