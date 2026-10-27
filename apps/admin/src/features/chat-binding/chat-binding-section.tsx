import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery } from "@tanstack/react-query";
import { useId, useState } from "react";
import { Controller, useForm } from "react-hook-form";
import { Button } from "../../components/ui/button.tsx";
import { Checkbox } from "../../components/ui/checkbox.tsx";
import { Field } from "../../components/ui/field.tsx";
import { Input } from "../../components/ui/input.tsx";
import { Label } from "../../components/ui/label.tsx";
import { NativeSelect } from "../../components/ui/native-select.tsx";
import { errorMessage, writeErrorMessage } from "../../lib/http.ts";
import { useAdminWriting } from "../../lib/query-client.ts";
import type { Provider } from "../providers/contracts.ts";
import { providerQueries } from "../providers/queries.ts";
import { chatBinding, type Binding } from "./contracts.ts";
import { chatBindingQueries, useSaveBinding } from "./queries.ts";

function ChatBindingForm({
  binding,
  providers,
  disabled,
}: {
  binding: Binding | null;
  providers: Provider[];
  disabled: boolean;
}) {
  const save = useSaveBinding();
  const [notice, setNotice] = useState("");
  const visionId = useId();
  const {
    control,
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<Binding>({
    resolver: zodResolver(chatBinding),
    defaultValues: binding ?? { providerId: "", model: "", vision: false },
  });

  function submit(input: Binding) {
    setNotice("");

    save.mutate(input, {
      onSuccess: () => {
        reset(input);
        setNotice("chat Binding 已保存。");
      },
    });
  }

  return (
    <form onSubmit={handleSubmit(submit)}>
      {/* Fields stay locked until the write and its refresh finish, so no edit is overwritten. */}
      <fieldset disabled={disabled} className="mt-6 grid gap-4 rounded-lg border border-border p-5">
        <Field label="Provider" error={errors.providerId?.message}>
          {(fieldProps) => (
            <NativeSelect {...fieldProps} {...register("providerId")}>
              <option value="" disabled>
                请选择 Provider
              </option>
              {providers.map((provider) => (
                <option key={provider.id} value={provider.id}>
                  {provider.name}
                </option>
              ))}
            </NativeSelect>
          )}
        </Field>
        <Field label="模型" error={errors.model?.message}>
          {(fieldProps) => <Input {...fieldProps} placeholder="gpt-5" {...register("model")} />}
        </Field>
        <Controller
          control={control}
          name="vision"
          render={({ field }) => (
            <div className="flex items-center gap-2">
              <Checkbox
                id={visionId}
                ref={field.ref}
                checked={field.value}
                onCheckedChange={(checked) => field.onChange(checked === true)}
                onBlur={field.onBlur}
              />
              <Label htmlFor={visionId}>支持图片输入</Label>
            </div>
          )}
        />
        {save.error && (
          <p role="alert" className="text-sm text-destructive">
            {writeErrorMessage(save.error)}
          </p>
        )}
        {notice && (
          <p role="status" className="text-sm text-green-700">
            {notice}
          </p>
        )}
        <div>
          <Button type="submit">{save.isPending ? "正在保存…" : "保存 Binding"}</Button>
        </div>
      </fieldset>
    </form>
  );
}

export function ChatBinding() {
  const capabilities = useQuery(chatBindingQueries.get());
  const providers = useQuery(providerQueries.list());
  const writing = useAdminWriting();
  const error = capabilities.error ?? providers.error;
  const disabled =
    writing || capabilities.isError || providers.isError || providers.data?.length === 0;

  return (
    <section aria-labelledby="binding-heading" className="mt-12">
      <h2 id="binding-heading" className="text-2xl font-semibold">
        chat Capability
      </h2>
      <p className="mt-2 text-sm text-muted-foreground">
        选择私聊使用的 Provider、模型和图片输入能力。
      </p>
      {(capabilities.isPending || providers.isPending) && (
        <p role="status" className="mt-6">
          正在加载 Binding…
        </p>
      )}
      {error && (
        <p role="alert" className="mt-6 text-destructive">
          {errorMessage(error)}
        </p>
      )}
      {error && (
        <Button
          type="button"
          variant="outline"
          className="mt-3"
          onClick={() => {
            void capabilities.refetch();
            void providers.refetch();
          }}
        >
          重新加载
        </Button>
      )}
      {capabilities.data?.chat === null && (
        <p className="mt-6 text-muted-foreground">尚未绑定 chat Capability。</p>
      )}
      {providers.data?.length === 0 && (
        <p className="mt-6 text-muted-foreground">尚未配置 Provider，请先添加 Provider。</p>
      )}
      {capabilities.data && providers.data && (
        <ChatBindingForm
          binding={capabilities.data.chat}
          providers={providers.data}
          disabled={disabled}
        />
      )}
    </section>
  );
}
