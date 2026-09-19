/** Mirrors of backend/app/schemas/auth.py. */

export type UserRole = "ADMIN" | "OPERATOR";

export interface User {
  id: string;
  email: string;
  display_name: string;
  role: UserRole;
  is_active: boolean;
  last_login_at: string | null;
  created_at: string;
}

export interface AuthStatus {
  auth_enabled: boolean;
  setup_required: boolean;
  user: User | null;
}

export interface SessionInfo {
  id: string;
  created_at: string;
  last_seen_at: string;
  expires_at: string;
  user_agent: string | null;
  ip_address: string | null;
  current: boolean;
}

export interface SetupWrite {
  email: string;
  display_name: string;
  password: string;
}

export interface LoginWrite {
  email: string;
  password: string;
}

export interface UserCreateWrite {
  email: string;
  display_name: string;
  password: string;
  role: UserRole;
}

export interface UserUpdateWrite {
  display_name?: string;
  role?: UserRole;
  is_active?: boolean;
}
