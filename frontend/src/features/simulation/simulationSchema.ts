import { z } from "zod";

/**
 * Mirrors `backend/app/schemas/simulation.py::SimulationWrite` bounds exactly.
 *
 * Plain `z.number()`, not `z.coerce.number()`: the inputs use
 * `register(name, { valueAsNumber: true })`, so React Hook Form already
 * converts to a number before validation runs. Coercing here too would make
 * the schema's input and output types diverge, which `zodResolver` cannot
 * reconcile with `useForm`'s single type parameter.
 */
export const simulationSchema = z
  .object({
    arrival_rate_per_min: z.number().min(0).max(200),
    service_rate_per_counter_per_min: z.number().gt(0).max(60),
    total_counters: z.number().int().min(0).max(32),
    active_counters: z.number().int().min(0).max(32),
    initial_queue: z.number().int().min(0).max(5000),
    duration_minutes: z.number().gt(0).max(180),
    arrival_growth_per_min: z.number().min(-20).max(20),
    surge_start_minute: z.number().min(0).max(180),
    seed: z.number().int().min(0),
  })
  .refine((data) => data.active_counters <= data.total_counters, {
    message: "Active counters cannot exceed total counters",
    path: ["active_counters"],
  });

export type SimulationFormValues = z.infer<typeof simulationSchema>;
