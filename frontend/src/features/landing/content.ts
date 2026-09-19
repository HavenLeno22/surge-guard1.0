/**
 * Every fact on the landing page, in one place, each with a source comment.
 * Nothing here is invented: figures, rule ids and vocabulary are read from
 * the backend and AI service, not written for effect.
 */

import type { OperationalIntelligenceReport } from "@/types/contracts";

export const precursors = [
  {
    // ai/surgeguard_ai/intelligence/stability.py: DENSITY_PRESSURE, weight 0.35
    title: "Crowd density",
    description:
      "How compressed the most crowded part of the view is, from a calibrated persons-per-square-metre grid where the camera geometry allows it.",
  },
  {
    // stability.py: MOTION_SUPPRESSION, weight 0.20
    title: "Movement suppression",
    description: "How far median walking speed has fallen below this camera's own measured baseline.",
  },
  {
    // stability.py: EGRESS_CONGESTION, weight 0.20
    title: "Exit congestion",
    description: "How full marked exits are relative to their configured clear width.",
  },
  {
    // stability.py: FLOW_CONFLICT, weight 0.15
    title: "Opposing flow",
    description: "How much of the crowd is moving against the majority heading.",
  },
  {
    // stability.py: RATE_OF_CHANGE, weight 0.10
    title: "Rate of change",
    description: "How fast conditions are worsening, independent of how bad they already are.",
  },
] as const;

export const pipelineStages = [
  {
    // backend/app/streaming/live_stream.py: FrameSource, reconnect with doubling backoff
    title: "Capture",
    detail: "USB, RTSP, DroidCam or a recorded clip, paced to the source's own frame rate.",
  },
  {
    // ai/surgeguard_ai: YOLO11 + ByteTrack
    title: "Perceive",
    detail: "YOLO11 person detection (CUDA FP16, or CPU with the fallback reason shown) and ByteTrack tracking.",
  },
  {
    title: "Measure",
    detail: "Density (persons/m² where calibrated, otherwise relative), flow against baseline, zone occupancy.",
  },
  {
    title: "Assess",
    detail: "The Crowd Stability Index: five weighted pressures, EMA-smoothed, banded Stable to Critical.",
  },
  {
    title: "Explain",
    detail: "The Evidence Engine states what changed, in operator language, with the metrics behind it.",
  },
  {
    title: "Advise",
    detail: "The Operational Intelligence Report: causes, confidence, and recommended actions from a closed vocabulary.",
  },
  {
    // backend/app/realtime: snapshot-first WebSocket, sequence numbers, resync, heartbeat
    title: "Deliver",
    detail: "One WebSocket per operator: snapshot first, sequence numbers, resync on gap, staleness shown.",
  },
] as const;

/** A worked example, not a live report - every id and label is real (decision_engine.py). */
export const exampleReport: OperationalIntelligenceReport = {
  sequence: 128,
  revision: 3,
  generated_at: new Date().toISOString(),
  frame_seq: 9042,
  status: "HIGH_ALERT",
  priority: "HIGH",
  csi: 27,
  confidence: 0.81,
  situation_summary:
    "Density is building at the west exit while the concourse behind it continues to fill.",
  primary_causes: [
    {
      indicator: "EGRESS_CONGESTION",
      label: "Exit congestion",
      contribution_pct: 46,
      pressure: 72,
      detail: "West exit throughput has fallen below its configured clear width.",
    },
    {
      indicator: "DENSITY_PRESSURE",
      label: "Crowd density",
      contribution_pct: 31,
      pressure: 58,
      detail: "Concourse density is approaching the calibrated upper bound.",
    },
  ],
  supporting_evidence: [],
  dominant_contributor_statement: "Exit congestion is the largest single contributor at 46%.",
  recommended_actions: [
    {
      priority: 1,
      recommendation_type: "OPEN_EXIT",
      action: "Open additional exit capacity at West Exit",
      rationale: "Clear width at this exit is the binding constraint on egress rate.",
      supporting_indicators: ["EGRESS_CONGESTION"],
      confidence: 0.84,
      urgency: "HIGH",
      zone_id: "west-exit",
      rule_id: "open-exit-zone",
    },
    {
      priority: 2,
      recommendation_type: "DEPLOY_PERSONNEL",
      action: "Deploy security personnel to the congested area",
      rationale: "Manual flow guidance reduces opposing movement at the neck.",
      supporting_indicators: ["DENSITY_PRESSURE"],
      confidence: 0.77,
      urgency: "HIGH",
      zone_id: null,
      rule_id: "deploy-personnel",
    },
  ],
  suppressed_actions: 0,
};

export const hardwareFacts = [
  {
    title: "USB, IP and phone cameras",
    // backend/app/streaming: usb/rtsp/droidcam/file source kinds
    detail: "USB webcams, RTSP/IP CCTV, Android phones running DroidCam, or a recorded clip in Demonstration Mode.",
  },
  {
    title: "Reconnection",
    detail: "A dropped source reconnects on a doubling backoff; the operator sees the state, not a blank tile.",
  },
  {
    title: "GPU or CPU",
    // ai/surgeguard_ai/perception: CUDA FP16 with CPU fallback and a reported reason
    detail: "Detection runs on CUDA with FP16 where available, and falls back to CPU with the reason shown.",
  },
  {
    title: "Connection tests",
    detail: "Every camera can be tested before it goes live: resolution, measured frame rate, and time to first frame.",
  },
] as const;

export const principles = [
  {
    title: "No face recognition",
    detail: "Detection finds people, not identities. Nothing about who someone is is captured or inferred.",
  },
  {
    // decision_service.py: track ids are per-camera and ephemeral, never matched across cameras
    title: "Ephemeral, per-camera tracking",
    detail: "Track identities exist only for as long as a person is in one camera's view, and are never matched across cameras.",
  },
  {
    // services/history_recorder.py: observation_bucket stores aggregates only, never frames
    title: "Aggregates-only history",
    detail: "Stored history is bucketed counts and averages. Frames and track identities are never persisted.",
  },
  {
    title: "Withheld, not guessed",
    detail: "A forecast or plan with incomplete inputs is withheld with a stated reason, never filled in with a guess.",
  },
] as const;
