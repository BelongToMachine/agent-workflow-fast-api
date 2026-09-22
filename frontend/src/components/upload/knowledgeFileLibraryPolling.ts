export type SingleFlightPoller = {
  dispose: () => void;
  run: () => Promise<boolean>;
};

export function createSingleFlightPoller(
  task: () => Promise<void>
): SingleFlightPoller {
  let disposed = false;
  let running = false;

  return {
    dispose() {
      disposed = true;
    },
    async run() {
      if (disposed || running) {
        return false;
      }
      running = true;
      try {
        await task();
        return true;
      } finally {
        running = false;
      }
    },
  };
}
