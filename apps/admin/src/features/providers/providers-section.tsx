import { zodResolver } from "@hookform/resolvers/zod";
import { useIsMutating, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Button } from "../../components/ui/button.tsx";
import { errorMessage, needsReconciliation } from "../../lib/http.ts";
import { providerCreate, providerFields, type Provider, type ProviderInput } from "./contracts.ts";
import { providerQueries, useDeleteProvider, useSaveProvider } from "./queries.ts";

const fieldClass =
  "mt-1 w-full rounded-md border border-border bg-background px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring/50";
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
  const save = useSaveProvider();
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
    save.mutate(
      { id: provider?.id ?? null, input },
      {
        onSuccess: () => {
          reset({ ...input, apiKey: "" });
          setNotice("Provider 已保存。");
        },
      },
    );
  }
  const error = save.error;
  return (
    <form
      className="mt-6 grid gap-4 rounded-lg border border-border p-5"
      onSubmit={handleSubmit(submit)}
    >
      <h3 className="font-medium">{provider ? "编辑 Provider" : "添加 Provider"}</h3>
      <div className="grid gap-4 sm:grid-cols-2">
        <label>
          名称
          <input className={fieldClass} autoComplete="off" {...register("name")} />
        </label>
        <label>
          协议
          <select className={fieldClass} {...register("protocol")}>
            <option value="openai">OpenAI</option>
            <option value="anthropic">Anthropic</option>
            <option value="google">Google</option>
          </select>
        </label>
      </div>
      <label>
        Base URL
        <input
          className={fieldClass}
          placeholder="https://api.openai.com/v1"
          {...register("baseUrl")}
        />
      </label>
      <label>
        API Key
        <input
          className={fieldClass}
          type="password"
          autoComplete="new-password"
          placeholder={provider ? `${provider.apiKeyMask}（留空保持不变）` : undefined}
          {...register("apiKey")}
        />
      </label>
      {Object.entries(errors).map(([name, field]) => (
        <p key={name} role="alert" className="text-sm text-red-700">
          {field.message}
        </p>
      ))}
      {error && (
        <p role="alert" className="text-sm text-red-700">
          {needsReconciliation(error)
            ? "请求结果未知，已尝试刷新配置，请确认后再重试。"
            : errorMessage(error)}
        </p>
      )}
      {notice && (
        <p role="status" className="text-sm text-green-700">
          {notice}
        </p>
      )}
      <div className="flex gap-2">
        <Button type="submit" disabled={disabled}>
          {save.isPending ? "正在保存…" : "保存 Provider"}
        </Button>
        {provider && (
          <Button type="button" variant="outline" disabled={disabled} onClick={onCancel}>
            取消
          </Button>
        )}
      </div>
    </form>
  );
}

export function Providers() {
  const providers = useQuery(providerQueries.list());
  const remove = useDeleteProvider();
  const [editingId, setEditingId] = useState<string | null>(null);
  const writing = useIsMutating({ mutationKey: ["admin-write"] }) > 0;
  const unavailable = writing || providers.isError;
  const editing = providers.data?.find((provider) => provider.id === editingId);
  const error = remove.error ?? providers.error;

  function deleteProvider(provider: Provider) {
    if (window.confirm(`删除 Provider「${provider.name}」？`)) remove.mutate(provider.id);
  }

  return (
    <section aria-labelledby="providers-heading" className="mt-12">
      <h2 id="providers-heading" className="text-2xl font-semibold">
        Providers
      </h2>
      <p className="mt-2 text-sm text-slate-600">
        配置模型服务及密钥。密钥只写不读，编辑时留空即可保留。
      </p>
      {providers.isPending && (
        <p role="status" className="mt-6">
          正在加载 Providers…
        </p>
      )}
      {error && (
        <p role="alert" className="mt-6 text-red-700">
          {remove.error && needsReconciliation(error)
            ? "请求结果未知，已尝试刷新配置，请确认后再重试。"
            : errorMessage(error)}
        </p>
      )}
      {providers.isError && (
        <Button
          type="button"
          variant="outline"
          className="mt-3"
          disabled={providers.isFetching}
          onClick={() => void providers.refetch()}
        >
          重新加载
        </Button>
      )}
      {providers.data?.length === 0 && <p className="mt-6 text-slate-600">尚未配置 Provider。</p>}
      <ul className="mt-6 grid gap-3">
        {providers.data?.map((provider) => (
          <li
            key={provider.id}
            className="flex flex-wrap items-center justify-between gap-4 rounded-lg border border-border p-4"
          >
            <div>
              <h3 className="font-medium">{provider.name}</h3>
              <p className="mt-1 text-sm text-slate-600">
                {provider.protocol} · {provider.baseUrl} · {provider.apiKeyMask}
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
