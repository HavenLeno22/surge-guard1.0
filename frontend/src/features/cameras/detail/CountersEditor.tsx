import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";

import { camerasApi } from "@/api/platform";
import { isApiError } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { CounterState } from "@/types/contracts";
import { Button } from "@/ui/Button";
import { Input } from "@/ui/Input";

function CounterRow({ cameraId, counter }: { cameraId: string; counter: CounterState }) {
  const queryClient = useQueryClient();
  const [active, setActive] = useState(counter.active_counters);
  const [rate, setRate] = useState(counter.service_rate_per_min);

  const mutation = useMutation({
    mutationFn: () =>
      camerasApi.setCounters(cameraId, counter.zone_id, {
        total_counters: counter.total_counters,
        active_counters: active,
        service_rate_per_min: rate,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.cameraCounters(cameraId) });
      toast.success(`${counter.zone_name} counters updated.`);
    },
    onError: (error) => toast.error(isApiError(error) ? error.message : "Could not update counters."),
  });

  const dirty = active !== counter.active_counters || rate !== counter.service_rate_per_min;

  return (
    <div className="flex flex-wrap items-end gap-3 rounded-control border border-line bg-surface-2/50 p-3">
      <div className="min-w-32 flex-1">
        <p className="text-sm text-ink">{counter.zone_name}</p>
        <p className="text-2xs text-ink-faint">{counter.total_counters} counters total, {counter.idle_counters} idle</p>
      </div>
      <label className="flex flex-col gap-1 text-xs text-ink-faint">
        Active counters
        <Input
          type="number"
          min={0}
          max={counter.total_counters}
          value={active}
          onChange={(event) => setActive(Number(event.target.value))}
          className="w-28"
        />
      </label>
      <label className="flex flex-col gap-1 text-xs text-ink-faint">
        Service rate / min
        <Input
          type="number"
          min={0}
          step="0.1"
          value={rate}
          onChange={(event) => setRate(Number(event.target.value))}
          className="w-28"
        />
      </label>
      <Button size="sm" variant="secondary" disabled={!dirty} loading={mutation.isPending} onClick={() => mutation.mutate()}>
        Save
      </Button>
    </div>
  );
}

export function CountersEditor({ cameraId, counters }: { cameraId: string; counters: CounterState[] }) {
  if (counters.length === 0) return <p className="text-xs text-ink-faint">No counter zones configured for this camera.</p>;

  return (
    <div className="flex flex-col gap-2">
      {counters.map((counter) => (
        <CounterRow key={counter.zone_id} cameraId={cameraId} counter={counter} />
      ))}
    </div>
  );
}
