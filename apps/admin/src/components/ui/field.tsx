import { useId, type ReactNode } from "react";
import { Label } from "./label.tsx";

type FieldControlProps = {
  id: string;
  "aria-invalid": boolean;
  "aria-describedby": string | undefined;
};

export function Field({
  label,
  error,
  children,
}: {
  label: string;
  error?: string | undefined;
  children: (props: FieldControlProps) => ReactNode;
}) {
  const id = useId();
  const errorId = `${id}-error`;

  return (
    <div className="grid gap-2">
      <Label htmlFor={id}>{label}</Label>
      {children({
        id,
        "aria-invalid": Boolean(error),
        "aria-describedby": error ? errorId : undefined,
      })}
      {error && (
        <p id={errorId} role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}
