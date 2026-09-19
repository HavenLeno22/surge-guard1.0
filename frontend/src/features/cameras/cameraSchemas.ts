import { z } from "zod";

const CAMERA_ROLES = ["GENERAL", "ENTRANCE", "WAITING_AREA", "QUEUE", "SERVICE", "EXIT"] as const;

export const cameraFormSchema = z.object({
  camera_id: z
    .string()
    .trim()
    .regex(/^[a-z0-9-]*$/, "Lowercase letters, numbers and hyphens only")
    .optional(),
  name: z.string().trim().min(1, "Name is required"),
  location: z.string().trim().optional(),
  role: z.enum(CAMERA_ROLES),
  stream_url: z.string().trim().optional(),
  demo_video_path: z.string().trim().optional(),
  coverage_area: z.string().trim().optional(),
  enabled: z.boolean(),
});

export type CameraFormValues = z.infer<typeof cameraFormSchema>;

export const CAMERA_ROLE_OPTIONS = CAMERA_ROLES.map((role) => ({ value: role, label: role }));
