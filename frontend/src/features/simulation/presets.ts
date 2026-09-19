import type { SimulationFormValues } from "./simulationSchema";

const BASE: SimulationFormValues = {
  arrival_rate_per_min: 6,
  service_rate_per_counter_per_min: 2,
  total_counters: 4,
  active_counters: 2,
  initial_queue: 10,
  duration_minutes: 12,
  arrival_growth_per_min: 0,
  surge_start_minute: 5,
  seed: 20260916,
};

export const SIMULATION_PRESETS: { name: string; description: string; values: SimulationFormValues }[] = [
  { name: "Steady state", description: "The backend's own defaults: gentle arrivals, no surge.", values: BASE },
  {
    name: "Sudden surge",
    description: "Arrivals accelerate sharply after minute 5, the abnormal-growth case.",
    values: { ...BASE, arrival_growth_per_min: 8, surge_start_minute: 5 },
  },
  {
    name: "Understaffed",
    description: "Only 1 of 4 counters open against steady demand.",
    values: { ...BASE, active_counters: 1, duration_minutes: 20 },
  },
];
