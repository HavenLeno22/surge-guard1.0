/**
 * The hero's "venue" instrument: a schematic crowd, not a recording. Pure and
 * seeded so it is testable, and so the same math that drives the animation
 * also drives the interactive index explorer (E3).
 *
 * The Crowd Stability Index formula is the real one (spec s1.1, `ai/surgeguard_ai
 * /intelligence/stability.py`): CSI = clamp(100 - sum(weight * pressure), 0, 100),
 * with unavailable indicators excluded and the remaining weights renormalised.
 */

import type { StabilityIndicator } from "@/types/contracts";
import { INDICATOR_DEFAULT_WEIGHT, INDICATOR_ORDER } from "@/lib/labels";

export function stabilityIndex(
  pressures: Record<StabilityIndicator, number>,
  weights: Record<StabilityIndicator, number> = INDICATOR_DEFAULT_WEIGHT,
  available: Partial<Record<StabilityIndicator, boolean>> = {},
): number {
  const usable = INDICATOR_ORDER.filter((indicator) => available[indicator] !== false);
  const totalWeight = usable.reduce((sum, indicator) => sum + weights[indicator], 0);
  if (totalWeight <= 0) return 100;
  const weightedPressure = usable.reduce(
    (sum, indicator) => sum + (weights[indicator] / totalWeight) * pressures[indicator],
    0,
  );
  return Math.min(Math.max(100 - weightedPressure, 0), 100);
}

// -- Deterministic RNG (mulberry32) --------------------------------------------

export function createRng(seed: number): () => number {
  let state = seed | 0;
  return () => {
    state = (state + 0x6d2b79f5) | 0;
    let t = Math.imul(state ^ (state >>> 15), 1 | state);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// -- Venue agents ---------------------------------------------------------------

export interface VenueAgent {
  id: number;
  x: number;
  y: number;
  vx: number;
  vy: number;
}

export interface VenueState {
  width: number;
  height: number;
  agents: VenueAgent[];
  elapsed: number;
  nextId: number;
}

export const VENUE_WIDTH = 640;
export const VENUE_HEIGHT = 360;
/** The queue neck: a deliberate bottleneck before the exit, where pressure builds. */
export const NECK = { xFrom: 420, xTo: 480, yFrom: 140, yTo: 220 };
const MAX_AGENTS = 46;

function spawnAgent(id: number, rng: () => number): VenueAgent {
  return {
    id,
    x: 16 + rng() * 30,
    y: 40 + rng() * (VENUE_HEIGHT - 80),
    vx: 16 + rng() * 10,
    vy: (rng() - 0.5) * 6,
  };
}

export function createVenue(seed: number): VenueState {
  const rng = createRng(seed);
  const agents: VenueAgent[] = [];
  for (let i = 0; i < 16; i += 1) agents.push(spawnAgent(i, rng));
  return { width: VENUE_WIDTH, height: VENUE_HEIGHT, agents, elapsed: 0, nextId: agents.length };
}

function channelTargetY(x: number, y: number): number {
  if (x < NECK.xFrom || x > NECK.xTo) return y;
  return Math.min(Math.max(y, NECK.yFrom + 16), NECK.yTo - 16);
}

/** One physics step. `rng` controls spawning only, so replaying a seed is optional. */
export function step(state: VenueState, dt: number, rng: () => number = Math.random): VenueState {
  const agents: VenueAgent[] = [];

  for (const agent of state.agents) {
    let neighbours = 0;
    for (const other of state.agents) {
      if (other.id === agent.id) continue;
      const dx = other.x - agent.x;
      const dy = other.y - agent.y;
      if (dx * dx + dy * dy < 34 * 34) neighbours += 1;
    }
    const crowding = Math.min(neighbours / 8, 1);
    const speedScale = 1 - crowding * 0.75;

    const targetY = channelTargetY(agent.x, agent.y);
    const vy = agent.vy + (targetY - agent.y) * 0.03;
    const x = agent.x + agent.vx * speedScale * dt;
    const y = Math.min(Math.max(agent.y + vy * speedScale * dt, 20), VENUE_HEIGHT - 20);

    if (x < state.width + 24) agents.push({ ...agent, x, y, vy });
  }

  let nextId = state.nextId;
  if (agents.length < MAX_AGENTS && rng() < dt * 0.9) {
    agents.push(spawnAgent(nextId, rng));
    nextId += 1;
  }

  return { ...state, agents, elapsed: state.elapsed + dt, nextId };
}

function bump(grid: number[][], row: number, col: number): void {
  const cells = grid[row];
  if (cells) cells[col] = (cells[col] ?? 0) + 1;
}

export function densityGrid(state: VenueState, cols = 16, rows = 9): number[][] {
  const grid: number[][] = Array.from({ length: rows }, () => new Array(cols).fill(0) as number[]);
  const cellWidth = state.width / cols;
  const cellHeight = state.height / rows;
  for (const agent of state.agents) {
    const col = Math.min(cols - 1, Math.max(0, Math.floor(agent.x / cellWidth)));
    const row = Math.min(rows - 1, Math.max(0, Math.floor(agent.y / cellHeight)));
    bump(grid, row, col);
  }
  return grid;
}

/** How packed the queue neck is, 0-100 - the pressure the hero's HUD band tracks. */
export function neckPressure(state: VenueState): number {
  let count = 0;
  for (const agent of state.agents) {
    if (agent.x >= NECK.xFrom - 30 && agent.x <= NECK.xTo + 10) count += 1;
  }
  return Math.min(100, (count / 13) * 100);
}

const FREE_FLOW_SPEED = 21; // the midpoint of spawnAgent's vx range

/**
 * Three of the five indicator pressures, read directly from the venue state.
 * The other two - opposing flow and a smoothed rate of change - are not
 * modelled by this schematic simulation, so they are marked unavailable
 * rather than faked: the same renormalisation `stabilityIndex` performs for
 * a real degraded camera.
 */
export function indicatorPressures(state: VenueState): {
  pressures: Record<StabilityIndicator, number>;
  available: Partial<Record<StabilityIndicator, boolean>>;
} {
  let egressCount = 0;
  for (const agent of state.agents) {
    if (agent.x >= NECK.xTo - 10 && agent.x <= NECK.xTo + 30) egressCount += 1;
  }
  const egress = Math.min(100, (egressCount / 8) * 100);

  const avgSpeed =
    state.agents.length === 0
      ? FREE_FLOW_SPEED
      : state.agents.reduce((sum, agent) => sum + Math.abs(agent.vx), 0) / state.agents.length;
  const motion = Math.min(100, Math.max(0, (1 - avgSpeed / FREE_FLOW_SPEED) * 100));

  return {
    pressures: {
      DENSITY_PRESSURE: neckPressure(state),
      MOTION_SUPPRESSION: motion,
      EGRESS_CONGESTION: egress,
      FLOW_CONFLICT: 0,
      RATE_OF_CHANGE: 0,
    },
    available: { FLOW_CONFLICT: false, RATE_OF_CHANGE: false },
  };
}
