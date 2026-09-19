import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { simulationApi } from "@/api/platform";
import { isApiError } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import { Panel } from "@/components/data/Panel";
import { PageHeader } from "@/features/shell/PageHeader";
import { Button } from "@/ui/Button";
import { SimulationForm } from "./SimulationForm";
import { SimulationResults } from "./SimulationResults";
import type { SimulationFormValues } from "./simulationSchema";

export function SimulationPage() {
  const queryClient = useQueryClient();

  const stateQuery = useQuery({
    queryKey: queryKeys.simulation,
    queryFn: async ({ signal }) => {
      try {
        return await simulationApi.state(signal);
      } catch (error) {
        if (isApiError(error) && error.isNotFound) return null; // "not run yet"
        throw error;
      }
    },
  });

  const runMutation = useMutation({
    mutationFn: (values: SimulationFormValues) => simulationApi.run(values),
    onSuccess: (result) => {
      queryClient.setQueryData(queryKeys.simulation, result.data);
    },
    onError: (error) => toast.error(isApiError(error) ? error.message : "The simulation could not be run."),
  });

  const resetMutation = useMutation({
    mutationFn: () => simulationApi.reset(),
    onSuccess: () => queryClient.setQueryData(queryKeys.simulation, null),
  });

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Simulation"
        description="What-if queue scenarios. The forecaster and allocator are the real ones; only the input is synthetic."
        actions={
          stateQuery.data && (
            <Button size="sm" variant="ghost" onClick={() => resetMutation.mutate()}>
              Reset
            </Button>
          )
        }
      />

      <Panel title="Parameters">
        <SimulationForm submitting={runMutation.isPending} onSubmit={(values) => runMutation.mutate(values)} />
      </Panel>

      <Panel title="Results" state={stateQuery.isPending ? "loading" : "ready"}>
        <SimulationResults result={stateQuery.data ?? runMutation.data?.data ?? null} />
      </Panel>
    </div>
  );
}
