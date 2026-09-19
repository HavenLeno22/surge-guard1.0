import { z } from "zod";

const email = z.email("Enter a valid email address").trim().min(1, "Email is required");
/** Matches the backend minimum (`auth/passwords.py`: PBKDF2, 12 characters). */
const newPassword = z.string().min(12, "Use at least 12 characters");

export const loginSchema = z.object({
  email,
  password: z.string().min(1, "Password is required"),
});
export type LoginFormValues = z.infer<typeof loginSchema>;

export const setupSchema = z
  .object({
    email,
    display_name: z.string().trim().min(1, "Name is required"),
    password: newPassword,
    confirm: z.string().min(1, "Confirm the password"),
  })
  .refine((data) => data.password === data.confirm, {
    message: "Passwords do not match",
    path: ["confirm"],
  });
export type SetupFormValues = z.infer<typeof setupSchema>;

export const changePasswordSchema = z
  .object({
    current_password: z.string().min(1, "Current password is required"),
    new_password: newPassword,
    confirm: z.string().min(1, "Confirm the new password"),
  })
  .refine((data) => data.new_password === data.confirm, {
    message: "Passwords do not match",
    path: ["confirm"],
  });
export type ChangePasswordFormValues = z.infer<typeof changePasswordSchema>;
