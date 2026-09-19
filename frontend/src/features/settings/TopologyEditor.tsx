import { Trash2 } from "lucide-react";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { siteApi } from "@/api/platform";
import { isApiError } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { TopologyLinkWrite } from "@/types/contracts";
import { Button } from "@/ui/Button";
import { IconButton } from "@/ui/IconButton";
import { Select } from "@/ui/Select";

export function TopologyEditor() {
  const queryClient = useQueryClient();
  const { data, isPending, isError, refetch } = useQuery({
    queryKey: queryKeys.topology,
    queryFn: ({ signal }) => siteApi.topology(signal),
  });

  const [fromCamera, setFromCamera] = useState("");
  const [fromZone, setFromZone] = useState("");
  const [toCamera, setToCamera] = useState("");
  const [toZone, setToZone] = useState("");

  const saveMutation = useMutation({
    mutationFn: (links: TopologyLinkWrite[]) => siteApi.saveTopology(links),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.topology });
      toast.success("Topology updated.");
    },
    onError: (error) => toast.error(isApiError(error) ? error.message : "Could not save the topology."),
  });

  if (isPending) return <p className="text-xs text-ink-faint">Loading…</p>;
  if (isError || !data) {
    return (
      <Button size="sm" variant="secondary" onClick={() => refetch()}>
        Retry
      </Button>
    );
  }
  if (data.load_error) {
    return <p className="text-sm text-critical-text">{data.load_error}</p>;
  }

  const cameraOptions = data.cameras.map((c) => ({ value: c.camera_id, label: c.name }));
  const zonesFor = (cameraId: string) =>
    data.zones.filter((z) => z.camera_id === cameraId).map((z) => ({ value: z.zone_id, label: z.name }));

  function addLink() {
    if (!data || !fromCamera || !fromZone || !toCamera || !toZone) return;
    const links: TopologyLinkWrite[] = [
      ...data.links.map((link) => ({
        from_camera_id: link.from_camera_id,
        from_zone_id: link.from_zone_id,
        to_camera_id: link.to_camera_id,
        to_zone_id: link.to_zone_id,
      })),
      { from_camera_id: fromCamera, from_zone_id: fromZone, to_camera_id: toCamera, to_zone_id: toZone },
    ];
    saveMutation.mutate(links);
    setFromCamera("");
    setFromZone("");
    setToCamera("");
    setToZone("");
  }

  function removeLink(linkId: string) {
    if (!data) return;
    const links = data.links
      .filter((link) => link.link_id !== linkId)
      .map((link) => ({
        from_camera_id: link.from_camera_id,
        from_zone_id: link.from_zone_id,
        to_camera_id: link.to_camera_id,
        to_zone_id: link.to_zone_id,
      }));
    saveMutation.mutate(links);
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-2">
        {data.links.length === 0 && <p className="text-xs text-ink-faint">No links yet - every camera is analysed independently.</p>}
        {data.links.map((link) => (
          <div key={link.link_id} className="flex items-center justify-between rounded-control border border-line bg-surface-2/50 px-3 py-2 text-sm">
            <span>
              {link.from_camera_id}/{link.from_zone_id} → {link.to_camera_id}/{link.to_zone_id}
              {link.crosses_cameras && <span className="ml-2 text-2xs text-ink-faint">cross-camera</span>}
            </span>
            <IconButton
              aria-label="Remove link"
              size="sm"
              variant="ghost"
              icon={<Trash2 size={14} />}
              onClick={() => removeLink(link.link_id)}
            />
          </div>
        ))}
      </div>

      <div className="flex flex-wrap items-end gap-2 rounded-control border border-line bg-surface-2/40 p-3">
        <Select aria-label="From camera" value={fromCamera} onValueChange={(v) => { setFromCamera(v); setFromZone(""); }} options={cameraOptions} placeholder="From camera" className="w-40" />
        <Select aria-label="From zone" value={fromZone} onValueChange={setFromZone} options={zonesFor(fromCamera)} placeholder="From zone" className="w-40" />
        <span className="text-ink-faint">→</span>
        <Select aria-label="To camera" value={toCamera} onValueChange={(v) => { setToCamera(v); setToZone(""); }} options={cameraOptions} placeholder="To camera" className="w-40" />
        <Select aria-label="To zone" value={toZone} onValueChange={setToZone} options={zonesFor(toCamera)} placeholder="To zone" className="w-40" />
        <Button
          size="sm"
          variant="secondary"
          disabled={!fromCamera || !fromZone || !toCamera || !toZone}
          loading={saveMutation.isPending}
          onClick={addLink}
        >
          Add link
        </Button>
      </div>
    </div>
  );
}
