"use client";

import { toast as sonnerToast } from "sonner";
import { Toast, type ToastProps } from "./toastContent";

export function toast(props: Omit<ToastProps, "id">) {
  return sonnerToast.custom((id) => (
    <Toast description={props.description} id={id} type={props.type} />
  ));
}
