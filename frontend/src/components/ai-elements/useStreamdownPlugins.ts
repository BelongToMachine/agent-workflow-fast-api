"use client";

import { cjk } from "@streamdown/cjk";
import type { PluginConfig } from "streamdown";
import { useEffect, useState } from "react";

const basePlugins: PluginConfig = { cjk };

export function useStreamdownPlugins() {
  const [plugins, setPlugins] = useState<PluginConfig>(basePlugins);

  useEffect(() => {
    let cancelled = false;

    Promise.all([
      import("@streamdown/code"),
      import("@streamdown/math"),
      import("@streamdown/mermaid"),
    ])
      .then(([codeModule, mathModule, mermaidModule]) => {
        if (cancelled) {
          return;
        }

        setPlugins({
          cjk,
          code: codeModule.code,
          math: mathModule.math,
          mermaid: mermaidModule.mermaid,
        });
      })
      .catch(() => {
        // Keep the base markdown renderer available if an optional plugin fails.
      });

    return () => {
      cancelled = true;
    };
  }, []);

  return plugins;
}
