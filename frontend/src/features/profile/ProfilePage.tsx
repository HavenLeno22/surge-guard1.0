import { zodResolver } from "@hookform/resolvers/zod";
import { LogOut } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { authApi } from "@/api/auth";
import { isApiError } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import { changePasswordSchema, type ChangePasswordFormValues } from "@/features/auth/authSchemas";
import { useAuthStatus } from "@/features/auth/useAuthStatus";
import { PageHeader } from "@/features/shell/PageHeader";
import { EmptyState } from "@/components/data/EmptyState";
import { ErrorState } from "@/components/data/ErrorState";
import { Panel } from "@/components/data/Panel";
import { formatDateTime } from "@/lib/format";
import { Button } from "@/ui/Button";
import { Field, fieldControlProps } from "@/ui/Field";
import { IconButton } from "@/ui/IconButton";
import { Input } from "@/ui/Input";

function NameField() {
  const { data: status } = useAuthStatus();
  const queryClient = useQueryClient();
  const [name, setName] = useState(status?.user?.display_name ?? "");

  const mutation = useMutation({
    mutationFn: (display_name: string) => authApi.updateMe(display_name),
    onSuccess: (user) => {
      queryClient.setQueryData(queryKeys.authStatus, (prev: typeof status) => (prev ? { ...prev, user } : prev));
      toast.success("Name updated.");
    },
    onError: (error) => toast.error(isApiError(error) ? error.message : "Could not update your name."),
  });

  return (
    <Field label="Display name" htmlFor="display_name">
      <div className="flex gap-2">
        <Input id="display_name" value={name} onChange={(event) => setName(event.target.value)} />
        <Button
          variant="secondary"
          disabled={!name.trim() || name === status?.user?.display_name}
          loading={mutation.isPending}
          onClick={() => mutation.mutate(name.trim())}
        >
          Save
        </Button>
      </div>
    </Field>
  );
}

function PasswordForm() {
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<ChangePasswordFormValues>({ resolver: zodResolver(changePasswordSchema) });

  const mutation = useMutation({
    mutationFn: (values: ChangePasswordFormValues) =>
      authApi.changePassword(values.current_password, values.new_password),
    onSuccess: () => {
      toast.success("Password changed. Other sessions were signed out.");
      reset();
    },
    onError: (error) =>
      toast.error(isApiError(error) && error.code === "INVALID_CREDENTIALS" ? "Current password is incorrect." : "Could not change the password."),
  });

  return (
    <form className="flex flex-col gap-4" onSubmit={handleSubmit((v) => mutation.mutate(v))}>
      <Field label="Current password" htmlFor="current_password" error={errors.current_password?.message}>
        <Input type="password" {...fieldControlProps("current_password", { error: errors.current_password?.message })} {...register("current_password")} />
      </Field>
      <Field label="New password" htmlFor="new_password" help="At least 12 characters." error={errors.new_password?.message}>
        <Input type="password" {...fieldControlProps("new_password", { error: errors.new_password?.message })} {...register("new_password")} />
      </Field>
      <Field label="Confirm new password" htmlFor="confirm" error={errors.confirm?.message}>
        <Input type="password" {...fieldControlProps("confirm", { error: errors.confirm?.message })} {...register("confirm")} />
      </Field>
      <Button type="submit" variant="primary" loading={isSubmitting || mutation.isPending} className="self-start">
        Change password
      </Button>
    </form>
  );
}

function SessionsPanel() {
  const queryClient = useQueryClient();
  const { data, isPending, isError, error: sessionsError, refetch } = useQuery({
    queryKey: queryKeys.sessions,
    queryFn: ({ signal }) => authApi.sessions(signal),
  });

  const revokeMutation = useMutation({
    mutationFn: (sessionId: string) => authApi.revokeSession(sessionId),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: queryKeys.sessions }),
    onError: (error) => toast.error(isApiError(error) ? error.message : "Could not revoke the session."),
  });

  if (isPending) return <p className="text-xs text-ink-faint">Loading…</p>;
  if (isError) {
    return (
      <ErrorState
        title="Sessions could not be loaded"
        description={isApiError(sessionsError) ? sessionsError.message : undefined}
        onRetry={() => void refetch()}
      />
    );
  }

  return (
    <div className="flex flex-col gap-2">
      {data?.map((session) => (
        <div key={session.id} className="flex items-center justify-between gap-3 rounded-control border border-line bg-surface-2/50 p-3">
          <div>
            <p className="text-sm text-ink">
              {session.current ? "This session" : session.user_agent ?? "Unknown device"}
            </p>
            <p className="text-2xs text-ink-faint">
              Last seen {formatDateTime(session.last_seen_at)}, expires {formatDateTime(session.expires_at)}
            </p>
          </div>
          {!session.current && (
            <IconButton
              aria-label="Revoke session"
              variant="danger"
              icon={<LogOut size={15} />}
              onClick={() => revokeMutation.mutate(session.id)}
            />
          )}
        </div>
      ))}
    </div>
  );
}

export function ProfilePage() {
  const { data: status } = useAuthStatus();

  if (status && !status.auth_enabled) {
    return (
      <div className="flex flex-col gap-5">
        <PageHeader title="Profile" />
        <Panel>
          <EmptyState
            title="Sign-in is turned off on this deployment"
            description="There are no operator accounts, so there is no name, password or session to manage. Set SURGEGUARD_AUTH_ENABLED=true on the backend to use accounts."
          />
        </Panel>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-5">
      <PageHeader title="Profile" description={status?.user?.email} />
      <Panel title="Name">
        <NameField />
      </Panel>
      <Panel title="Password">
        <PasswordForm />
      </Panel>
      <Panel title="Active sessions">
        <SessionsPanel />
      </Panel>
    </div>
  );
}
