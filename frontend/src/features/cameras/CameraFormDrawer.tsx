import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { Controller, useForm, useWatch } from "react-hook-form";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { camerasApi } from "@/api/platform";
import { isApiError } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { Camera, ConnectionTestRead } from "@/types/contracts";
import { Button } from "@/ui/Button";
import { Drawer } from "@/ui/Drawer";
import { Field, fieldControlProps } from "@/ui/Field";
import { Input } from "@/ui/Input";
import { Select } from "@/ui/Select";
import { Switch } from "@/ui/Switch";
import { CAMERA_ROLE_OPTIONS, type CameraFormValues, cameraFormSchema } from "./cameraSchemas";
import { ConnectionTestResult } from "./ConnectionTestResult";

export function CameraFormDrawer({
  open,
  onOpenChange,
  camera,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  camera?: Camera;
}) {
  const queryClient = useQueryClient();
  const isEdit = Boolean(camera);
  const [testResult, setTestResult] = useState<ConnectionTestRead | null>(null);

  const {
    register,
    handleSubmit,
    control,
    formState: { errors, isSubmitting },
  } = useForm<CameraFormValues>({
    resolver: zodResolver(cameraFormSchema),
    defaultValues: camera
      ? {
          camera_id: camera.camera_id,
          name: camera.name,
          location: camera.location,
          role: camera.role,
          stream_url: camera.stream_url ?? "",
          demo_video_path: camera.demo_video_path ?? "",
          coverage_area: camera.coverage_area,
          enabled: camera.enabled,
        }
      : { role: "GENERAL", enabled: true },
  });

  const testMutation = useMutation({
    mutationFn: (url: string) => camerasApi.testAddress(url, camera?.camera_id),
    onSuccess: setTestResult,
    onError: (error) => toast.error(isApiError(error) ? error.message : "Connection test failed."),
  });

  const saveMutation = useMutation({
    mutationFn: async (values: CameraFormValues) => {
      const body = {
        name: values.name,
        location: values.location || undefined,
        role: values.role,
        stream_url: values.stream_url || null,
        demo_video_path: values.demo_video_path || null,
        coverage_area: values.coverage_area || undefined,
        enabled: values.enabled,
      };
      if (isEdit && camera) return camerasApi.update(camera.camera_id, body);
      return camerasApi.add({ ...body, camera_id: values.camera_id || null });
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.cameras });
      toast.success(isEdit ? "Camera updated." : "Camera added.");
      onOpenChange(false);
    },
    onError: (error) => toast.error(isApiError(error) ? error.message : "Could not save the camera."),
  });

  const streamUrl = useWatch({ control, name: "stream_url" });

  return (
    <Drawer
      open={open}
      onOpenChange={onOpenChange}
      title={isEdit ? "Edit camera" : "Add camera"}
      footer={
        <>
          <Button variant="secondary" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            variant="primary"
            loading={isSubmitting || saveMutation.isPending}
            onClick={handleSubmit((values) => saveMutation.mutate(values))}
          >
            {isEdit ? "Save changes" : "Add camera"}
          </Button>
        </>
      }
    >
      <form className="flex flex-col gap-4" onSubmit={(event) => event.preventDefault()}>
        {!isEdit && (
          <Field
            label="Camera ID"
            htmlFor="camera_id"
            help="Lowercase letters, numbers and hyphens. Auto-generated if left blank."
            error={errors.camera_id?.message}
          >
            <Input
              {...fieldControlProps("camera_id", { error: errors.camera_id?.message })}
              {...register("camera_id")}
            />
          </Field>
        )}
        <Field label="Name" htmlFor="name" error={errors.name?.message}>
          <Input {...fieldControlProps("name", { error: errors.name?.message })} {...register("name")} />
        </Field>
        <Field label="Location" htmlFor="location" error={errors.location?.message}>
          <Input {...fieldControlProps("location", {})} {...register("location")} />
        </Field>
        <Field label="Role" htmlFor="role">
          <Controller
            control={control}
            name="role"
            render={({ field }) => (
              <Select id="role" value={field.value} onValueChange={field.onChange} options={CAMERA_ROLE_OPTIONS} />
            )}
          />
        </Field>
        <Field
          label="Stream URL"
          htmlFor="stream_url"
          help="RTSP/HTTP address, or leave blank for a USB device / DroidCam default."
          error={errors.stream_url?.message}
        >
          <Input {...fieldControlProps("stream_url", {})} {...register("stream_url")} />
        </Field>
        <Field
          label="Demo clip path"
          htmlFor="demo_video_path"
          help="Used only in Demonstration Mode."
          error={errors.demo_video_path?.message}
        >
          <Input {...fieldControlProps("demo_video_path", {})} {...register("demo_video_path")} />
        </Field>
        <Field label="Coverage area" htmlFor="coverage_area" error={errors.coverage_area?.message}>
          <Input {...fieldControlProps("coverage_area", {})} {...register("coverage_area")} />
        </Field>
        <div className="flex items-center justify-between">
          <span className="text-sm text-ink-secondary">Enabled</span>
          <Controller
            control={control}
            name="enabled"
            render={({ field }) => (
              <Switch aria-label="Camera enabled" checked={field.value} onCheckedChange={field.onChange} />
            )}
          />
        </div>

        <Button
          type="button"
          variant="secondary"
          loading={testMutation.isPending}
          disabled={!streamUrl}
          onClick={() => streamUrl && testMutation.mutate(streamUrl)}
        >
          Test connection
        </Button>
        {testResult && <ConnectionTestResult result={testResult} />}
      </form>
    </Drawer>
  );
}
