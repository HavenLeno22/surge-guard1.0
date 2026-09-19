import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { Controller, useForm } from "react-hook-form";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { z } from "zod";

import { usersApi } from "@/api/auth";
import { isApiError } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { User, UserRole } from "@/types/auth";
import { Button } from "@/ui/Button";
import { Dialog } from "@/ui/Dialog";
import { Field, fieldControlProps } from "@/ui/Field";
import { Input } from "@/ui/Input";
import { Select } from "@/ui/Select";
import { Switch } from "@/ui/Switch";

const ROLE_OPTIONS = [
  { value: "OPERATOR", label: "Operator" },
  { value: "ADMIN", label: "Administrator" },
];

const createSchema = z.object({
  email: z.email("Enter a valid email address"),
  display_name: z.string().trim().min(1, "Name is required"),
  password: z.string().min(12, "Use at least 12 characters"),
  role: z.enum(["ADMIN", "OPERATOR"] as [UserRole, UserRole]),
});
type CreateValues = z.infer<typeof createSchema>;

function AddOperatorDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const queryClient = useQueryClient();
  const {
    register,
    handleSubmit,
    control,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<CreateValues>({ resolver: zodResolver(createSchema), defaultValues: { role: "OPERATOR" } });

  const mutation = useMutation({
    mutationFn: (values: CreateValues) => usersApi.create(values),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.users });
      toast.success("Operator added.");
      reset();
      onOpenChange(false);
    },
    onError: (error) => toast.error(isApiError(error) ? error.message : "Could not add the operator."),
  });

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="Add operator"
      footer={
        <>
          <Button variant="secondary" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button variant="primary" loading={isSubmitting || mutation.isPending} onClick={handleSubmit((v) => mutation.mutate(v))}>
            Add
          </Button>
        </>
      }
    >
      <form className="flex flex-col gap-4" onSubmit={(event) => event.preventDefault()}>
        <Field label="Name" htmlFor="display_name" error={errors.display_name?.message}>
          <Input {...fieldControlProps("display_name", { error: errors.display_name?.message })} {...register("display_name")} />
        </Field>
        <Field label="Email" htmlFor="email" error={errors.email?.message}>
          <Input type="email" {...fieldControlProps("email", { error: errors.email?.message })} {...register("email")} />
        </Field>
        <Field label="Password" htmlFor="password" help="At least 12 characters." error={errors.password?.message}>
          <Input type="password" {...fieldControlProps("password", { error: errors.password?.message })} {...register("password")} />
        </Field>
        <Field label="Role" htmlFor="role">
          <Controller
            control={control}
            name="role"
            render={({ field }) => <Select id="role" value={field.value} onValueChange={field.onChange} options={ROLE_OPTIONS} />}
          />
        </Field>
      </form>
    </Dialog>
  );
}

function OperatorRow({ user }: { user: User }) {
  const queryClient = useQueryClient();
  const mutation = useMutation({
    mutationFn: (patch: { role?: UserRole; is_active?: boolean }) => usersApi.update(user.id, patch),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: queryKeys.users }),
    onError: (error) => toast.error(isApiError(error) ? error.message : "Could not update the operator."),
  });

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-control border border-line bg-surface-2/50 p-3">
      <div>
        <p className="text-sm text-ink">{user.display_name}</p>
        <p className="text-2xs text-ink-faint">{user.email}</p>
      </div>
      <div className="flex items-center gap-3">
        <Select
          aria-label={`Role for ${user.display_name}`}
          value={user.role}
          onValueChange={(role) => mutation.mutate({ role: role as UserRole })}
          options={ROLE_OPTIONS}
          className="w-40"
        />
        <div className="flex items-center gap-2">
          <span className="text-xs text-ink-faint">Active</span>
          <Switch
            aria-label={`Active: ${user.display_name}`}
            checked={user.is_active}
            onCheckedChange={(is_active) => mutation.mutate({ is_active })}
          />
        </div>
      </div>
    </div>
  );
}

export function OperatorsPanel() {
  const [addOpen, setAddOpen] = useState(false);
  const { data, isPending, isError, refetch } = useQuery({
    queryKey: queryKeys.users,
    queryFn: ({ signal }) => usersApi.list(signal),
  });

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <span className="text-sm text-ink-secondary">Accounts are deactivated, never deleted.</span>
        <Button size="sm" variant="secondary" onClick={() => setAddOpen(true)}>
          Add operator
        </Button>
      </div>
      {isPending && <p className="text-xs text-ink-faint">Loading…</p>}
      {isError && (
        <Button size="sm" variant="secondary" onClick={() => refetch()}>
          Retry
        </Button>
      )}
      {data && (
        <div className="flex flex-col gap-2">
          {data.map((user) => (
            <OperatorRow key={user.id} user={user} />
          ))}
        </div>
      )}
      <AddOperatorDialog open={addOpen} onOpenChange={setAddOpen} />
    </div>
  );
}
