import { Link } from "react-router";

import { TimelineList } from "@/components/intel/TimelineList";
import { Panel } from "@/components/data/Panel";
import { useNow } from "@/lib/hooks/useNow";
import { useLive } from "@/realtime/store";
import { Button } from "@/ui/Button";

export function LiveTimeline() {
  const timeline = useLive((state) => state.timeline);
  const now = useNow(5000);

  return (
    <Panel
      title="Timeline"
      actions={
        <Button asChild size="sm" variant="ghost">
          <Link to="/timeline">View all</Link>
        </Button>
      }
      state={timeline.length === 0 ? "empty" : "ready"}
      stateMessage="No timeline entries yet."
    >
      <TimelineList entries={timeline.slice(0, 12)} now={now} />
    </Panel>
  );
}
