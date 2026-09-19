import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { useNavigate } from "react-router";
import { useQueryClient } from "@tanstack/react-query";

import { authApi } from "@/api/auth";
import { isApiError } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import { Button } from "@/ui/Button";
import { Field, fieldControlProps } from "@/ui/Field";
import { Input } from "@/ui/Input";
import { AuthLayout } from "./AuthLayout";
import { type SetupFormValues, setupSchema } from "./authSchemas";

/** First-run only: creates the first ADMIN account. `POST /auth/setup` refuses once one exists. */
export function SetupPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [formError, setFormError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<SetupFormValues>({ resolver: zodResolver(setupSchema) });

  async function onSubmit(values: SetupFormValues) {
    setFormError(null);
    try {
      const user = await authApi.setup({
        email: values.email,
        display_name: values.display_name,
        password: values.password,
      });
      queryClient.setQueryData(queryKeys.authStatus, {
        auth_enabled: true,
        setup_required: false,
        user,
      });
      navigate("/command-center", { replace: true });
    } catch (error) {
      if (isApiError(error) && error.code === "SETUP_COMPLETE") {
        setFormError("An administrator account already exists. Sign in instead.");
      } else if (isApiError(error)) {
        setFormError(error.message);
      } else {
        setFormError("Setup failed. Try again.");
      }
    }
  }

  return (
    <AuthLayout
      title="Set up SurgeGuard"
      subtitle="Create the first administrator account for this deployment."
    >
      <form className="flex flex-col gap-4" onSubmit={handleSubmit(onSubmit)} noValidate>
        <Field label="Name" htmlFor="display_name" error={errors.display_name?.message}>
          <Input
            autoComplete="name"
            {...fieldControlProps("display_name", { error: errors.display_name?.message })}
            {...register("display_name")}
          />
        </Field>
        <Field label="Email" htmlFor="email" error={errors.email?.message}>
          <Input
            type="email"
            autoComplete="email"
            {...fieldControlProps("email", { error: errors.email?.message })}
            {...register("email")}
          />
        </Field>
        <Field
          label="Password"
          htmlFor="password"
          help="At least 12 characters."
          error={errors.password?.message}
        >
          <Input
            type="password"
            autoComplete="new-password"
            {...fieldControlProps("password", { error: errors.password?.message })}
            {...register("password")}
          />
        </Field>
        <Field label="Confirm password" htmlFor="confirm" error={errors.confirm?.message}>
          <Input
            type="password"
            autoComplete="new-password"
            {...fieldControlProps("confirm", { error: errors.confirm?.message })}
            {...register("confirm")}
          />
        </Field>
        {formError && (
          <p role="alert" className="text-sm text-critical-text">
            {formError}
          </p>
        )}
        <Button type="submit" variant="primary" size="lg" loading={isSubmitting}>
          Create administrator account
        </Button>
      </form>
    </AuthLayout>
  );
}
