import { parse, unparse } from "papaparse";
import { toast } from "sonner";
import { Artifact } from "@/components/chat/createArtifact";
import {
  CopyIcon,
  LineChartIcon,
  RedoIcon,
  SparklesIcon,
  UndoIcon,
} from "@/components/chat/icons";
import { SpreadsheetEditor } from "@/components/chat/sheetEditor";
import { i18n } from "@/lib/i18n";

type Metadata = Record<string, never>;

export const sheetArtifact = new Artifact<"sheet", Metadata>({
  actions: [
    {
      description: "artifacts.viewPreviousVersion",
      icon: <UndoIcon size={18} />,
      isDisabled: ({ currentVersionIndex }) => {
        if (currentVersionIndex === 0) {
          return true;
        }

        return false;
      },
      onClick: ({ handleVersionChange }) => {
        handleVersionChange("prev");
      },
    },
    {
      description: "artifacts.viewNextVersion",
      icon: <RedoIcon size={18} />,
      isDisabled: ({ isCurrentVersion }) => {
        if (isCurrentVersion) {
          return true;
        }

        return false;
      },
      onClick: ({ handleVersionChange }) => {
        handleVersionChange("next");
      },
    },
    {
      description: "artifacts.copyAsCsv",
      icon: <CopyIcon />,
      onClick: ({ content }) => {
        const parsed = parse<string[]>(content, { skipEmptyLines: true });

        const nonEmptyRows = parsed.data.filter((row) =>
          row.some((cell) => cell.trim() !== "")
        );

        const cleanedCsv = unparse(nonEmptyRows);

        navigator.clipboard.writeText(cleanedCsv);
        toast.success(i18n.t("common.copiedCsv"));
      },
    },
  ],
  content: ({ content, currentVersionIndex, onSaveContent, status }) => (
    <SpreadsheetEditor
      content={content}
      currentVersionIndex={currentVersionIndex}
      isCurrentVersion={true}
      saveContent={onSaveContent}
      status={status}
    />
  ),
  description: "artifacts.sheetDescription",
  initialize: () => null,
  kind: "sheet",
  onStreamPart: ({ setArtifact, streamPart }) => {
    if (streamPart.type === "data-sheetDelta") {
      setArtifact((draftArtifact) => ({
        ...draftArtifact,
        content: streamPart.data,
        isVisible: true,
        status: "streaming",
      }));
    }
  },
  toolbar: [
    {
      description: "artifacts.formatData",
      icon: <SparklesIcon />,
      onClick: ({ sendMessage }) => {
        sendMessage({
          parts: [
            { text: "Can you please format and clean the data?", type: "text" },
          ],
          role: "user",
        });
      },
    },
    {
      description: "artifacts.analyzeData",
      icon: <LineChartIcon />,
      onClick: ({ sendMessage }) => {
        sendMessage({
          parts: [
            {
              text: "Can you please analyze and visualize the data by creating a new code artifact in python?",
              type: "text",
            },
          ],
          role: "user",
        });
      },
    },
  ],
});
