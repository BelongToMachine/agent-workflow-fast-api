import { describe, expect, test } from "bun:test";
import { createSingleFlightPoller } from "./knowledgeFileLibraryPolling";

describe("createSingleFlightPoller", () => {
  test("does not start a second poll while the first poll is pending", async () => {
    let calls = 0;
    let release: (() => void) | undefined;
    const firstPoll = new Promise<void>((resolve) => {
      release = resolve;
    });
    const poller = createSingleFlightPoller(async () => {
      calls += 1;
      await firstPoll;
    });

    const running = poller.run();
    expect(await poller.run()).toBe(false);
    expect(calls).toBe(1);

    release?.();
    expect(await running).toBe(true);
    expect(await poller.run()).toBe(true);
    expect(calls).toBe(2);
  });

  test("stops accepting polls after disposal", async () => {
    const poller = createSingleFlightPoller(async () => undefined);

    poller.dispose();

    expect(await poller.run()).toBe(false);
  });
});
