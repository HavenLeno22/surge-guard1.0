import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";

import { Button } from "@/ui/Button";
import { Field, fieldControlProps } from "@/ui/Field";
import { Input } from "@/ui/Input";
import { SIMULATION_PRESETS } from "./presets";
import { type SimulationFormValues, simulationSchema } from "./simulationSchema";

const FIELDS: { name: keyof SimulationFormValues; label: string; step?: string }[] = [
  { name: "arrival_rate_per_min", label: "Arrival rate (people/min)", step: "0.1" },
  { name: "service_rate_per_counter_per_min", label: "Service rate per counter (people/min)", step: "0.1" },
  { name: "total_counters", label: "Total counters" },
  { name: "active_counters", label: "Active counters" },
  { name: "initial_queue", label: "Starting queue" },
  { name: "duration_minutes", label: "Duration (minutes)", step: "0.5" },
  { name: "arrival_growth_per_min", label: "Arrival growth (people/min, per min)", step: "0.1" },
  { name: "surge_start_minute", label: "Surge starts at minute", step: "0.5" },
  { name: "seed", label: "Random seed" },
];

export function SimulationForm({
  onSubmit,
  submitting,
}: {
  onSubmit: (values: SimulationFormValues) => void;
  submitting: boolean;
}) {
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<SimulationFormValues>({
    resolver: zodResolver(simulationSchema),
    defaultValues: SIMULATION_PRESETS[0]?.values,
  });

  return (
    <form className="flex flex-col gap-4" onSubmit={handleSubmit(onSubmit)}>
      <div className="flex flex-wrap gap-2">
        {SIMULATION_PRESETS.map((preset) => (
          <Button key={preset.name} type="button" size="sm" variant="secondary" onClick={() => reset(preset.values)}>
            {preset.name}
          </Button>
        ))}
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        {FIELDS.map((field) => (
          <Field key={field.name} label={field.label} htmlFor={field.name} error={errors[field.name]?.message}>
            <Input
              type="number"
              step={field.step ?? "1"}
              {...fieldControlProps(field.name, { error: errors[field.name]?.message })}
              {...register(field.name, { valueAsNumber: true })}
            />
          </Field>
        ))}
      </div>
      <Button type="submit" variant="primary" loading={submitting}>
        Run simulation
      </Button>
    </form>
  );
}
