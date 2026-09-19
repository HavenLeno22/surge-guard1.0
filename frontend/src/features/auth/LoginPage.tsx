import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { useNavigate, useSearchParams } from "react-router";
import { useQueryClient } from "@tanstack/react-query";

import { authApi } from "@/api/auth";
import { isApiError } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import { Button } from "@/ui/Button";
import { Field, fieldControlProps } from "@/ui/Field";
import { Input } from "@/ui/Input";
import { AuthLayout } from "./AuthLayout";
import { type LoginFormValues, loginSchema } from "./authSchemas";

/** Seconds left until a rate-limited retry is allowed, ticking down each second. */
function useCountdown(initial: number): number {
  const [prevInitial, setPrevInitial] = useState(initial);
  const [remaining, setRemaining] = useState(initial);
  if (initial !== prevInitial) {
    setPrevInitial(initial);
    setRemaining(initial);
  }
  useEffect(() => {
    if (remaining <= 0) return;
    const timer = setInterval(() => setRemaining((s) => Math.max(0, s - 1)), 1000);
    return () => clearInterval(timer);
  }, [remaining]);
  return remaining;
}

export function LoginPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const queryClient = useQueryClient();
  const [formError, setFormError] = useState<string | null>(null);
  const [retryAfter, setRetryAfter] = useState(0);
  const countdown = useCountdown(retryAfter);

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<LoginFormValues>({ resolver: zodResolver(loginSchema) });

  async function onSubmit(values: LoginFormValues) {
    setFormError(null);
    try {
      const user = await authApi.login(values);
      queryClient.setQueryData(queryKeys.authStatus, {
        auth_enabled: true,
        setup_required: false,
        user,
      });
      const next = params.get("next");
      navigate(next && next.startsWith("/") ? next : "/command-center", { replace: true });
    } catch (error) {
      if (isApiError(error)) {
        if (error.code === "TOO_MANY_ATTEMPTS") {
          setRetryAfter(error.retryAfterSeconds ?? 60);
          setFormError("Too many attempts. Wait before trying again.");
        } else if (error.code === "INVALID_CREDENTIALS") {
          setFormError("Incorrect email or password.");
        } else {
          setFormError(error.message);
        }
      } else {
        setFormError("Sign-in failed. Try again.");
      }
    }
  }

  const locked = countdown > 0;

  return (
    <AuthLayout title="Sign in" subtitle="Enter your SurgeGuard operator credentials.">
      <form className="flex flex-col gap-4" onSubmit={handleSubmit(onSubmit)} noValidate>
        <Field label="Email" htmlFor="email" error={errors.email?.message}>
          <Input
            type="email"
            autoComplete="email"
            {...fieldControlProps("email", { error: errors.email?.message })}
            {...register("email")}
          />
        </Field>
        <Field label="Password" htmlFor="password" error={errors.password?.message}>
          <Input
            type="password"
            autoComplete="current-password"
            {...fieldControlProps("password", { error: errors.password?.message })}
            {...register("password")}
          />
        </Field>
        {formError && (
          <p role="alert" className="text-sm text-critical-text">
            {formError}
            {locked && ` (${countdown}s)`}
          </p>
        )}
        <Button type="submit" variant="primary" size="lg" loading={isSubmitting} disabled={locked}>
          Sign in
        </Button>
      </form>
    </AuthLayout>
  );
}
