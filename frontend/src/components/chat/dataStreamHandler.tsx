"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { useActiveChat } from "@/hooks/useActiveChat";
import { initialArtifactData, useArtifact } from "@/hooks/useArtifact";
import { upsertChatHistory } from "@/lib/backend/chatHistoryCache";
import {
  backendQueryKeys,
  useBackendIdentity,
} from "@/lib/backend/reactQuery";
import { artifactDefinitions } from "./artifact";
import { useDataStream } from "./dataStreamProvider";

export function DataStreamHandler() {
  const { dataStream, setDataStream } = useDataStream();
  const queryClient = useQueryClient();
  const identity = useBackendIdentity();
  const { chatId, visibilityType } = useActiveChat();

  const { artifact, setArtifact, setMetadata } = useArtifact();

  useEffect(() => {
    if (!dataStream?.length) {
      return;
    }

    const newDeltas = dataStream.slice();
    setDataStream([]);

    for (const delta of newDeltas) {
      if (delta.type === "data-chat-title") {
        upsertChatHistory(
          queryClient,
          backendQueryKeys.chatHistory(identity),
          {
            createdAt: new Date(),
            id: chatId,
            title: delta.data,
            userId: identity,
            visibility: visibilityType,
          },
          { replaceExistingTitle: true }
        );
        continue;
      }
      const artifactDefinition = artifactDefinitions.find(
        (currentArtifactDefinition) =>
          currentArtifactDefinition.kind === artifact.kind
      );

      if (artifactDefinition?.onStreamPart) {
        artifactDefinition.onStreamPart({
          setArtifact,
          setMetadata,
          streamPart: delta,
        });
      }

      setArtifact((draftArtifact) => {
        if (!draftArtifact) {
          return { ...initialArtifactData, status: "streaming" };
        }

        switch (delta.type) {
          case "data-id":
            return {
              ...draftArtifact,
              documentId: delta.data,
              status: "streaming",
            };

          case "data-title":
            return {
              ...draftArtifact,
              status: "streaming",
              title: delta.data,
            };

          case "data-kind":
            return {
              ...draftArtifact,
              kind: delta.data,
              status: "streaming",
            };

          case "data-clear":
            return {
              ...draftArtifact,
              content: "",
              status: "streaming",
            };

          case "data-finish":
            return {
              ...draftArtifact,
              status: "idle",
            };

          default:
            return draftArtifact;
        }
      });
    }
  }, [
    artifact,
    chatId,
    dataStream,
    identity,
    queryClient,
    setArtifact,
    setDataStream,
    setMetadata,
    visibilityType,
  ]);

  return null;
}
