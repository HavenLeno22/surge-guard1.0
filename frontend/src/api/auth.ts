import type {
  AuthStatus,
  LoginWrite,
  SessionInfo,
  SetupWrite,
  User,
  UserCreateWrite,
  UserUpdateWrite,
} from "@/types/auth";

import { apiRequest, apiRequestEnvelope } from "./client";

export const authApi = {
  status: (signal?: AbortSignal) => apiRequest<AuthStatus>("/auth/status", { signal }),
  setup: (body: SetupWrite) => apiRequest<User>("/auth/setup", { method: "POST", body }),
  login: (body: LoginWrite) => apiRequest<User>("/auth/login", { method: "POST", body }),
  logout: () => apiRequest<null>("/auth/logout", { method: "POST" }),
  me: (signal?: AbortSignal) => apiRequest<User>("/auth/me", { signal }),
  updateMe: (display_name: string) =>
    apiRequest<User>("/auth/me", { method: "PATCH", body: { display_name } }),
  changePassword: (current_password: string, new_password: string) =>
    apiRequestEnvelope<null>("/auth/me/password", {
      method: "POST",
      body: { current_password, new_password },
    }),
  sessions: (signal?: AbortSignal) => apiRequest<SessionInfo[]>("/auth/sessions", { signal }),
  revokeSession: (sessionId: string) =>
    apiRequest<null>(`/auth/sessions/${encodeURIComponent(sessionId)}`, { method: "DELETE" }),
};

export const usersApi = {
  list: (signal?: AbortSignal) => apiRequest<User[]>("/users", { signal }),
  create: (body: UserCreateWrite) => apiRequest<User>("/users", { method: "POST", body }),
  update: (userId: string, body: UserUpdateWrite) =>
    apiRequest<User>(`/users/${encodeURIComponent(userId)}`, { method: "PATCH", body }),
};
