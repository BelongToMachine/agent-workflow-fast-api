import { ReactQueryDevtools } from "@tanstack/react-query-devtools";
import { useTranslation } from "react-i18next";
import { useEffect, useRef, useState } from "react";

type Point = {
  x: number;
  y: number;
};

const STORAGE_KEY = "asianode.query-devtools-position";
const EDGE_GAP = 12;
const HANDLE_SIZE = 22;

function clampPoint(point: Point): Point {
  if (typeof window === "undefined") {
    return point;
  }

  return {
    x: Math.max(EDGE_GAP, Math.min(point.x, window.innerWidth - HANDLE_SIZE - EDGE_GAP)),
    y: Math.max(EDGE_GAP, Math.min(point.y, window.innerHeight - HANDLE_SIZE - EDGE_GAP)),
  };
}

function readStoredPoint(): Point {
  if (typeof window === "undefined") {
    return { x: 16, y: 16 };
  }

  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (!stored) {
      return { x: window.innerWidth - 76, y: 16 };
    }

    const point = JSON.parse(stored) as Partial<Point>;
    if (typeof point.x !== "number" || typeof point.y !== "number") {
      return { x: window.innerWidth - 76, y: 16 };
    }

    return clampPoint(point as Point);
  } catch {
    return { x: window.innerWidth - 76, y: 16 };
  }
}

export function DraggableQueryDevtools() {
  const { t } = useTranslation();
  const [point, setPoint] = useState<Point>(readStoredPoint);
  const [isDragging, setIsDragging] = useState(false);
  const dragState = useRef<{
    offsetX: number;
    offsetY: number;
  } | null>(null);

  useEffect(() => {
    const handleResize = () => setPoint((current) => clampPoint(current));
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  useEffect(() => {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(point));
  }, [point]);

  const handlePointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) {
      return;
    }

    dragState.current = {
      offsetX: event.clientX - point.x,
      offsetY: event.clientY - point.y,
    };
    setIsDragging(true);
    event.currentTarget.setPointerCapture(event.pointerId);
  };

  const handlePointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!dragState.current) {
      return;
    }

    setPoint(
      clampPoint({
        x: event.clientX - dragState.current.offsetX,
        y: event.clientY - dragState.current.offsetY,
      })
    );
  };

  const handlePointerUp = (event: React.PointerEvent<HTMLDivElement>) => {
    dragState.current = null;
    setIsDragging(false);
    event.currentTarget.releasePointerCapture(event.pointerId);
  };

  return (
    <div
      style={{
        alignItems: "center",
        display: "flex",
        gap: 4,
        left: point.x,
        position: "fixed",
        top: point.y,
        zIndex: 100001,
      }}
    >
      <div
        aria-label={t("ui.dragQueryDevtools")}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        role="button"
        style={{
          alignItems: "center",
          background: "rgba(17, 24, 39, 0.8)",
          border: "1px solid rgba(255, 255, 255, 0.24)",
          borderRadius: 6,
          color: "rgba(255, 255, 255, 0.9)",
          cursor: isDragging ? "grabbing" : "grab",
          display: "flex",
          fontSize: 14,
          height: HANDLE_SIZE,
          justifyContent: "center",
          touchAction: "none",
          userSelect: "none",
          width: HANDLE_SIZE,
        }}
        tabIndex={0}
        title={t("ui.dragQueryDevtools")}
      >
        ⠿
      </div>
      <ReactQueryDevtools
        buttonPosition="relative"
        initialIsOpen={false}
        position="top"
      />
    </div>
  );
}
