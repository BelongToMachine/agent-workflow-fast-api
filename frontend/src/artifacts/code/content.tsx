import { useCallback } from "react";
import { CodeEditor } from "@/components/chat/codeEditor";
import { Console, type ConsoleOutput } from "@/components/chat/console";
import type { ArtifactContent } from "@/components/chat/createArtifact";

export type CodeArtifactMetadata = {
  outputs: ConsoleOutput[];
};

export function CodeArtifactContent({
  metadata,
  setMetadata,
  ...props
}: ArtifactContent<CodeArtifactMetadata>) {
  const clearConsoleOutputs = useCallback(() => {
    setMetadata((currentMetadata) => ({
      ...currentMetadata,
      outputs: [],
    }));
  }, [setMetadata]);

  return (
    <>
      <div className="relative min-h-[200px]">
        <CodeEditor {...props} />
      </div>

      {metadata?.outputs ? (
        <Console
          consoleOutputs={metadata.outputs}
          setConsoleOutputs={clearConsoleOutputs}
        />
      ) : null}
    </>
  );
}
