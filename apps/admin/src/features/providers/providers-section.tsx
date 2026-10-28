import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Button } from "../../components/ui/button.tsx";
import { Field } from "../../components/ui/field.tsx";
import { Input } from "../../components/ui/input.tsx";
import { NativeSelect } from "../../components/ui/native-select.tsx";
import { errorMessage, writeErrorMessage } from "../../lib/http.ts";
import { useAdminWriting } from "../../lib/query-client.ts";
import {
  protocolLabels,
  providerCreate,
  providerFields,
  providerProtocol,
  type Provider,
  type ProviderInput,
} from "./contracts.ts";
import {
  providerQueries,
  useCreateProvider,
  useDeleteProvider,
  useUpdateProvider,
} from "./queries.ts";

const emptyProvider: ProviderInput = { name: "", protocol: "openai", baseUrl: "", apiKey: "" };

function ProviderForm({
  provider,
  disabled,
  onCancel,
}: {
  provider: Provider | null;
  disabled: boolean;
  onCancel: () => void;
}) {
  const create = useCreateProvider();
  const update = useUpdateProvider();
  const save = provider ? update : create;
  const [notice, setNotice] = useState("");
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<ProviderInput>({
    resolver: zodResolver(provider ? providerFields : providerCreate),
    defaultValues: provider
      ? { name: provider.name, protocol: provider.protocol, baseUrl: provider.baseUrl, apiKey: "" }
      : emptyProvider,
  });

  function submit(input: ProviderInput) {
    setNotice("");

    const options = {
      onSuccess: () => {
        // An edit keeps the saved fields on screen; a create starts the next Provider from scratch.
        reset(provider ? { ...input, apiKey: "" } : emptyProvider);
        setNotice("Provider 已保存。");
      },
    };

    if (!provider) return create.mutate(input, options);

    // An empty replacement key keeps the saved credential.
    const { apiKey, ...fields } = input;
    update.mutate({ id: provider.id, patch: apiKey ? input : fields }, options);
  }

  return (
    <form className="mt-6 rounded-lg border border-border p-5" onSubmit={handleSubmit(submit)}>
      <h3 className="font-medium">{provider ? "编辑 Provider" : "添加 Provider"}</h3>
      {/* Fields stay locked until the write and its refresh finish, so no edit is overwritten. */}
      <fieldset disabled={disabled} className="mt-4 grid gap-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="名称" error={errors.name?.message}>
            {(fieldProps) => <Input {...fieldProps} autoComplete="off" {...register("name")} />}
          </Field>
          <Field label="协议" error={errors.protocol?.message}>
            {(fieldProps) => (
              <NativeSelect {...fieldProps} {...register("protocol")}>
                {providerProtocol.options.map((protocol) => (
                  <option key={protocol} value={protocol}>
                    {protocolLabels[protocol]}
                  </option>
                ))}
              </NativeSelect>
            )}
          </Field>
        </div>
        <Field label="Base URL" error={errors.baseUrl?.message}>
          {(fieldProps) => (
            <Input
              {...fieldProps}
              placeholder="https://api.openai.com/v1"
              {...register("baseUrl")}
            />
          )}
        </Field>
        <Field label="API Key" error={errors.apiKey?.message}>
          {(fieldProps) => (
            <Input
              {...fieldProps}
              type="password"
              autoComplete="new-password"
              placeholder={provider ? `${provider.apiKeyMask}（留空保持不变）` : undefined}
              {...register("apiKey")}
            />
          )}
        </Field>
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
        <div className="flex gap-2">
          <Button type="submit">{save.isPending ? "正在保存…" : "保存 Provider"}</Button>
          {provider && (
            <Button type="button" variant="outline" onClick={onCancel}>
              取消
            </Button>
          )}
        </div>
      </fieldset>
    </form>
  );
}

export function Providers() {
  const providers = useQuery(providerQueries.list());
  const remove = useDeleteProvider();
  const [editingId, setEditingId] = useState<string | null>(null);
  const unavailable = useAdminWriting() || providers.isError;
  const editing = providers.data?.find((provider) => provider.id === editingId);

  function deleteProvider(provider: Provider) {
    if (window.confirm(`删除 Provider「${provider.name}」？`)) remove.mutate(provider.id);
  }

  return (
    <section aria-labelledby="providers-heading" className="mt-12">
      <h2 id="providers-heading" className="text-2xl font-semibold">
        Providers
      </h2>
      <p className="mt-2 text-sm text-muted-foreground">
        配置模型服务及密钥。密钥只写不读，编辑时留空即可保留。
      </p>
      {providers.isPending && (
        <p role="status" className="mt-6">
          正在加载 Providers…
        </p>
      )}
      {remove.error && (
        <p role="alert" className="mt-6 text-destructive">
          {writeErrorMessage(remove.error)}
        </p>
      )}
      {providers.isError && (
        <>
          <p role="alert" className="mt-6 text-destructive">
            {errorMessage(providers.error)}
          </p>
          <Button
            type="button"
            variant="outline"
            className="mt-3"
            disabled={providers.isFetching}
            onClick={() => void providers.refetch()}
          >
            重新加载
          </Button>
        </>
      )}
      {providers.data?.length === 0 && (
        <p className="mt-6 text-muted-foreground">尚未配置 Provider。</p>
      )}
      <ul className="mt-6 grid gap-3">
        {providers.data?.map((provider) => (
          <li
            key={provider.id}
            className="flex flex-wrap items-center justify-between gap-4 rounded-lg border border-border p-4"
          >
            <div>
              <h3 className="font-medium">{provider.name}</h3>
              <p className="mt-1 text-sm text-muted-foreground">
                {protocolLabels[provider.protocol]} · {provider.baseUrl} · {provider.apiKeyMask}
              </p>
            </div>
            <div className="flex gap-2">
              <Button
                type="button"
                variant="outline"
                disabled={unavailable}
                aria-label={`编辑 ${provider.name}`}
                onClick={() => setEditingId(provider.id)}
              >
                编辑
              </Button>
              <Button
                type="button"
                variant="destructive"
                disabled={unavailable}
                aria-label={`删除 ${provider.name}`}
                onClick={() => deleteProvider(provider)}
              >
                删除
              </Button>
            </div>
          </li>
        ))}
      </ul>
      {providers.data && (
        <ProviderForm
          key={editing?.id ?? "new"}
          provider={editing ?? null}
          disabled={unavailable}
          onCancel={() => setEditingId(null)}
        />
      )}
    </section>
  );
}
