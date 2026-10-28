import type { ComponentProps } from "react";
import { ChevronDownIcon } from "lucide-react";
import { cn } from "../../lib/utils.ts";

function NativeSelect({ className, ...props }: ComponentProps<"select">) {
  return (
    <div
      className="relative w-full has-[select:disabled]:opacity-50"
      data-slot="native-select-wrapper"
    >
      <select
        data-slot="native-select"
        className={cn(
          "h-9 w-full min-w-0 appearance-none rounded-md border border-input bg-transparent px-3 py-2 pr-9 text-sm shadow-xs outline-none disabled:pointer-events-none disabled:cursor-not-allowed",
          "focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 aria-invalid:border-destructive aria-invalid:ring-destructive/20",
          className,
        )}
        {...props}
      />
      <ChevronDownIcon
        className="pointer-events-none absolute top-1/2 right-3 size-4 -translate-y-1/2 opacity-50"
        aria-hidden="true"
      />
    </div>
  );
}

export { NativeSelect };
