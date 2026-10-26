import type { ReactNode } from "react";

interface NoticeProps {
  tone: "error" | "info";
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}

/**
 * Inline message block. Errors use `role="alert"` so they are announced and
 * can be located by automated browsers; informational notices are static.
 */
export function Notice({ tone, title, children, action }: NoticeProps) {
  const isError = tone === "error";
  return (
    <div
      role={isError ? "alert" : undefined}
      className={`rounded-md border-[1.5px] px-5 py-4 ${
        isError ? "border-alarm-edge bg-alarm-wash text-alarm" : "border-stone bg-mist text-spruce"
      }`}
    >
      <p className="font-extrabold">{title}</p>
      {children ? <div className={`mt-1 ${isError ? "text-spruce" : "text-moss"}`}>{children}</div> : null}
      {action ? <div className="mt-3">{action}</div> : null}
    </div>
  );
}
