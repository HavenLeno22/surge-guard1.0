/** Mirrors of backend/app/schemas/hardware.py. */

export type HardwareLevel = "NORMAL" | "WARNING" | "CRITICAL" | "NO_DATA";

export type HardwareCommand =
  | HardwareLevel
  | "TEST_RED"
  | "TEST_GREEN"
  | "TEST_BLUE"
  | "TEST_YELLOW"
  | "TEST_WARNING_TONE"
  | "TEST_ALARM"
  | "TEST_SEQUENCE"
  | "TEST_OFF";

export interface HardwareStatus {
  enabled: boolean;
  connected: boolean;
  port: string | null;
  firmware: string | null;
  mode: "live" | "test";
  level: HardwareLevel;
  reason: string;
  camera_id: string | null;
  csi: number | null;
  commanded: HardwareCommand | null;
  commanded_at: string | null;
  acknowledged: HardwareCommand | null;
  acknowledged_at: string | null;
  last_error: string | null;
  test_command: HardwareCommand | null;
  test_expires_at: string | null;
}

export interface HardwareTestWrite {
  command: HardwareCommand;
  duration_seconds?: number;
}
