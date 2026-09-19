import { Panel } from "@/components/data/Panel";
import { useIsAdmin } from "@/features/auth/useIsAdmin";
import { PageHeader } from "@/features/shell/PageHeader";
import { OperatorsPanel } from "./OperatorsPanel";
import { PreferencesPanel } from "./PreferencesPanel";
import { TopologyEditor } from "./TopologyEditor";

export function SettingsPage() {
  const isAdmin = useIsAdmin();

  return (
    <div className="flex flex-col gap-5">
      <PageHeader title="Settings" />

      <Panel title="Preferences" meta="This device">
        <PreferencesPanel />
      </Panel>

      {isAdmin && (
        <>
          <Panel title="Site topology" meta="Admin">
            <TopologyEditor />
          </Panel>
          <Panel title="Operators" meta="Admin">
            <OperatorsPanel />
          </Panel>
        </>
      )}
    </div>
  );
}
