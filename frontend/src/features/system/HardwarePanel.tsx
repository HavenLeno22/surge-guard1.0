import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";

import { hardwareApi } from "@/api/platform";
import { isApiError } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import { EmptyState } from "@/components/data/EmptyState";
import { KeyValueList } from "@/components/data/KeyValueList";
import { Panel } from "@/components/data/Panel";
import { cn } from "@/lib/cn";
import { formatClock, formatCsi } from "@/lib/format";
import { useNow } from "@/lib/hooks/useNow";
import { TONE_HEX } from "@/lib/status";
import type { HardwareCommand, HardwareLevel, HardwareStatus } from "@/types/hardware";
import { Button } from "@/ui/Button";

/**
 * What the physical LED and buzzer do for each command. The swatch is the LED's
 * real colour, labelled - this panel describes a device, and every swatch
 * carries its colour and meaning in words.
 */
const OUTPUT: Record<HardwareCommand, { label: string; led: string; swatch: string | null; sound: string }> = {
  NORMAL: { label: "Normal", led: "Green", swatch: TONE_HEX.stable, sound: "Silent" },
  WARNING: { label: "Warning", led: "Yellow", swatch: TONE_HEX.attention, sound: "Quiet chirp every 1.5 s" },
  CRITICAL: { label: "Critical", led: "Red", swatch: TONE_HEX.critical, sound: "Two-tone alarm" },
  NO_DATA: { label: "No data", led: "Blue", swatch: TONE_HEX.observe, sound: "Silent" },
  TEST_RED: { label: "Red", led: "Red", swatch: TONE_HEX.critical, sound: "Silent" },
  TEST_GREEN: { label: "Green", led: "Green", swatch: TONE_HEX.stable, sound: "Silent" },
  TEST_BLUE: { label: "Blue", led: "Blue", swatch: TONE_HEX.observe, sound: "Silent" },
  TEST_YELLOW: { label: "Yellow", led: "Yellow", swatch: TONE_HEX.attention, sound: "Silent" },
  TEST_WARNING_TONE: { label: "Warning tone", led: "Off", swatch: null, sound: "Quiet chirp every 1.5 s" },
  TEST_ALARM: { label: "Alarm tone", led: "Off", swatch: null, sound: "Two-tone alarm" },
  TEST_SEQUENCE: { label: "Full sequence", led: "Each colour in turn", swatch: null, sound: "Chirp, then alarm" },
  TEST_OFF: { label: "All off", led: "Off", swatch: null, sound: "Silent" },
};

const LEVEL_TESTS: HardwareCommand[] = ["NORMAL", "WARNING", "CRITICAL", "NO_DATA"];
const PART_TESTS: HardwareCommand[] = [
  "TEST_RED",
  "TEST_GREEN",
  "TEST_BLUE",
  "TEST_YELLOW",
  "TEST_WARNING_TONE",
  "TEST_ALARM",
  "TEST_SEQUENCE",
  "TEST_OFF",
];
const DURATIONS = [10, 30, 60];

function LedSwatch({ command }: { command: HardwareCommand | null }) {
  const output = command ? OUTPUT[command] : null;
  return (
    <span
      aria-hidden="true"
      className={cn("inline-block size-4 shrink-0 rounded-full border border-line-strong", !output?.swatch && "bg-surface-3")}
      style={output?.swatch ? { backgroundColor: output.swatch, boxShadow: `0 0 12px ${output.swatch}66` } : undefined}
    />
  );
}

function levelLabel(level: HardwareLevel): string {
  return OUTPUT[level].label;
}

function Showing({ status, now }: { status: HardwareStatus; now: number }) {
  const showing = status.acknowledged ?? status.commanded;
  const confirmed = status.acknowledged !== null && status.acknowledged === status.commanded;
  const output = showing ? OUTPUT[showing] : null;
  const secondsLeft = status.test_expires_at
    ? Math.max(0, Math.ceil((Date.parse(status.test_expires_at) - now) / 1000))
    : null;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-3">
        <LedSwatch command={showing} />
        <div className="flex min-w-0 flex-col">
          <span className="text-lg font-semibold text-ink-strong">
            {output ? output.label : "Nothing sent yet"}
            {status.mode === "test" && <span className="ml-2 text-sm font-normal text-attention">Test</span>}
          </span>
          {output && (
            <span className="text-xs text-ink-muted">
              LED {output.led.toLowerCase()}, {output.sound.toLowerCase()}
            </span>
          )}
        </div>
      </div>
      <p className="text-xs text-ink-muted">
        {!status.connected
          ? "Not connected, so the board is not being updated."
          : confirmed && status.acknowledged_at
            ? `The board confirmed this at ${formatClock(status.acknowledged_at)}.`
            : "Waiting for the board to confirm the last command."}
        {status.mode === "test" && secondsLeft !== null && ` Test ends in ${secondsLeft} s.`}
      </p>
    </div>
  );
}

/** The Arduino RGB LED and buzzer: what it shows, why, and a test mode that needs no crowd event. */
export function HardwarePanel() {
  const queryClient = useQueryClient();
  const now = useNow(1000);
  const [duration, setDuration] = useState(DURATIONS[0] ?? 10);

  const query = useQuery({
    queryKey: queryKeys.hardware,
    queryFn: ({ signal }) => hardwareApi.status(signal),
    refetchInterval: 2000,
  });
  const status = query.data;

  const startTest = useMutation({
    mutationFn: (command: HardwareCommand) => hardwareApi.startTest({ command, duration_seconds: duration }),
    onSuccess: (data, command) => {
      queryClient.setQueryData(queryKeys.hardware, data);
      toast(`Testing ${OUTPUT[command].label.toLowerCase()} for ${duration} s.`);
    },
    onError: (error) => toast.error(isApiError(error) ? error.message : "The hardware test could not start."),
  });
  const stopTest = useMutation({
    mutationFn: () => hardwareApi.stopTest(),
    onSuccess: (data) => {
      queryClient.setQueryData(queryKeys.hardware, data);
      toast("Test stopped. Following the Decision Engine again.");
    },
    onError: (error) => toast.error(isApiError(error) ? error.message : "The hardware test could not be stopped."),
  });

  const meta = status?.enabled
    ? status.connected
      ? `Connected on ${status.port ?? "serial"}`
      : "Not connected"
    : undefined;

  return (
    <Panel
      title="Alert hardware"
      meta={meta}
      state={query.isPending ? "loading" : query.isError ? "error" : "ready"}
      stateMessage={isApiError(query.error) ? query.error.message : "Alert hardware status could not be loaded."}
      onRetry={() => void query.refetch()}
    >
      {status && !status.enabled && (
        <EmptyState
          title="Alert hardware is not enabled on this deployment"
          description="Attach the Arduino with the SurgeGuard alert sketch, then set SURGEGUARD_HARDWARE_ENABLED=true on the backend."
        />
      )}

      {status?.enabled && (
        <div className="flex flex-col gap-5">
          <div className="grid gap-5 md:grid-cols-2">
            <Showing status={status} now={now} />

            <div className="flex flex-col gap-2">
              <span className="text-xs text-ink-faint">Decision Engine calls for</span>
              <span className="flex items-center gap-2 text-sm font-medium text-ink">
                <LedSwatch command={status.level} />
                {levelLabel(status.level)}
                {status.csi !== null && <span className="text-ink-muted">CSI {formatCsi(status.csi)}</span>}
              </span>
              <p className="text-xs text-ink-muted">{status.reason}</p>
            </div>
          </div>

          {status.last_error && (
            <p className="rounded-control border border-attention/30 bg-attention/5 px-3 py-2 text-xs text-ink-secondary">
              {status.last_error}
            </p>
          )}

          <KeyValueList
            items={[
              { label: "Mode", value: status.mode === "test" ? "Hardware test" : "Live, following the Decision Engine" },
              { label: "Firmware", value: status.firmware ?? "—" },
              { label: "Last command", value: status.commanded ? `${OUTPUT[status.commanded].label}${status.commanded_at ? ` at ${formatClock(status.commanded_at)}` : ""}` : "—" },
            ]}
          />

          <div className="flex flex-col gap-3 border-t border-line pt-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 className="text-sm font-semibold text-ink-strong">Test the hardware</h3>
              <div className="flex flex-wrap items-center gap-2 text-xs text-ink-muted">
                <span aria-hidden="true">Run for</span>
                <fieldset className="inline-flex min-w-0 rounded-control border border-line-strong p-0.5">
                  <legend className="sr-only">Test duration</legend>
                  {DURATIONS.map((seconds) => (
                    <button
                      key={seconds}
                      type="button"
                      aria-pressed={seconds === duration}
                      onClick={() => setDuration(seconds)}
                      className={cn(
                        "min-h-8 rounded-sm px-2.5 text-xs font-medium",
                        seconds === duration ? "bg-surface-2 text-ink-strong" : "text-ink-muted hover:text-ink",
                      )}
                    >
                      {seconds} s
                    </button>
                  ))}
                </fieldset>
                {status.mode === "test" && (
                  <Button size="sm" variant="secondary" loading={stopTest.isPending} onClick={() => stopTest.mutate()}>
                    Stop test
                  </Button>
                )}
              </div>
            </div>
            <p className="text-xs text-ink-muted">
              A test overrides live monitoring for the chosen time, then the hardware follows the Decision Engine again.
            </p>
            <div className="flex flex-wrap gap-2">
              {LEVEL_TESTS.map((command) => (
                <Button
                  key={command}
                  size="sm"
                  variant="secondary"
                  disabled={!status.connected || startTest.isPending}
                  onClick={() => startTest.mutate(command)}
                  iconStart={<LedSwatch command={command} />}
                >
                  {OUTPUT[command].label}
                </Button>
              ))}
            </div>
            <div className="flex flex-wrap gap-2">
              {PART_TESTS.map((command) => (
                <Button
                  key={command}
                  size="sm"
                  variant="ghost"
                  disabled={!status.connected || startTest.isPending}
                  onClick={() => startTest.mutate(command)}
                >
                  {OUTPUT[command].label}
                </Button>
              ))}
            </div>
          </div>
        </div>
      )}
    </Panel>
  );
}
