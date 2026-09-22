import type { ComponentProps } from "react";

export function Image({ alt, ...props }: ComponentProps<"img">) {
  return <img alt={alt ?? ""} {...props} />;
}
