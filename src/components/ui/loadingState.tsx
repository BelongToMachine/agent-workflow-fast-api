export function LoadingState({ message }: { message: string }) {
  return (
    <main
      aria-busy="true"
      className="flex min-h-dvh items-center justify-center bg-background px-6 text-center"
    >
      <div aria-live="polite" className="flex flex-col items-center gap-4" role="status">
        <p className="text-sm text-muted-foreground">{message}</p>
        <div aria-hidden="true" className="relative size-10 text-foreground">
          <svg
            className="size-full"
            fill="none"
            viewBox="0 0 48 48"
            xmlns="http://www.w3.org/2000/svg"
          >
            <circle
              className="text-foreground/10"
              cx="24"
              cy="24"
              r="14"
              stroke="currentColor"
              strokeWidth="1.5"
            />
            <circle
              className="workspace-loading-orbit text-foreground/70"
              cx="24"
              cy="24"
              r="14"
              stroke="currentColor"
              strokeDasharray="28 79"
              strokeLinecap="round"
              strokeWidth="1.5"
            />
          </svg>
        </div>
      </div>
    </main>
  );
}
