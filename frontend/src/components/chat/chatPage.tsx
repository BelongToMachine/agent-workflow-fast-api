import { ActiveChatProvider } from "@/hooks/useActiveChat";
import { DataStreamProvider } from "./dataStreamProvider";
import { ChatShell } from "./shell";

export function ChatPage() {
  return (
    <DataStreamProvider>
      <ActiveChatProvider>
        <ChatShell />
      </ActiveChatProvider>
    </DataStreamProvider>
  );
}
