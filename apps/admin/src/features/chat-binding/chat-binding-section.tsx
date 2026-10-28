import { zodResolver } from "@hookform/resolvers/zod";
import { useIsMutating, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Button } from "../../components/ui/button.tsx";
import { errorMessage, needsReconciliation } from "../../lib/http.ts";
import type { Provider } from "../providers/contracts.ts";
import { providerQueries } from "../providers/queries.ts";
import { chatBinding, type Binding } from "./contracts.ts";
import { chatBindingQueries, useSaveBinding } from "./queries.ts";

const fieldClass =
  "mt-1 w-full rounded-md border border-border bg-background px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring/50";

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
  const {
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
    <form
      className="mt-6 grid gap-4 rounded-lg border border-border p-5"
      onSubmit={handleSubmit(submit)}
    >
      <label>
        Provider
        <select className={fieldClass} {...register("providerId")}>
          <option value="" disabled>
            请选择 Provider
          </option>
          {providers.map((provider) => (
            <option key={provider.id} value={provider.id}>
              {provider.name}
            </option>
          ))}
        </select>
      </label>
      <label>
        模型
        <input className={fieldClass} placeholder="gpt-5" {...register("model")} />
      </label>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" {...register("vision")} />
        支持图片输入
      </label>
      {Object.entries(errors).map(([name, field]) => (
        <p key={name} role="alert" className="text-sm text-red-700">
          {field.message}
        </p>
      ))}
      {save.error && (
        <p role="alert" className="text-sm text-red-700">
          {needsReconciliation(save.error)
            ? "请求结果未知，已尝试刷新配置，请确认后再重试。"
            : errorMessage(save.error)}
        </p>
      )}
      {notice && (
        <p role="status" className="text-sm text-green-700">
          {notice}
        </p>
      )}
      <div>
        <Button type="submit" disabled={disabled}>
          {save.isPending ? "正在保存…" : "保存 Binding"}
        </Button>
      </div>
    </form>
  );
}

export function ChatBinding() {
  const capabilities = useQuery(chatBindingQueries.get());
  const providers = useQuery(providerQueries.list());
  const writing = useIsMutating({ mutationKey: ["admin-write"] }) > 0;
  const error = capabilities.error ?? providers.error;
  const disabled =
    writing || capabilities.isError || providers.isError || providers.data?.length === 0;

  return (
    <section aria-labelledby="binding-heading" className="mt-12">
      <h2 id="binding-heading" className="text-2xl font-semibold">
        chat Capability
      </h2>
      <p className="mt-2 text-sm text-slate-600">选择私聊使用的 Provider、模型和图片输入能力。</p>
      {(capabilities.isPending || providers.isPending) && (
        <p role="status" className="mt-6">
          正在加载 Binding…
        </p>
      )}
      {error && (
        <p role="alert" className="mt-6 text-red-700">
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
        <p className="mt-6 text-slate-600">尚未绑定 chat Capability。</p>
      )}
      {providers.data?.length === 0 && (
        <p className="mt-6 text-slate-600">尚未配置 Provider，请先添加 Provider。</p>
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
