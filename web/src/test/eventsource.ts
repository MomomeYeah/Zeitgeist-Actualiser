/**
 * The SSE transport tests drive by hand.
 *
 * `EventTarget` gives it `addEventListener` and `dispatchEvent` for free,
 * which is the whole of the interface `useRunEvents` uses — so this is a
 * real implementation of the seam rather than a mock of one.
 */
import type { LogLine } from "@/api/types";

export class FakeEventSource extends EventTarget {
  static instances: FakeEventSource[] = [];

  closed = false;

  constructor(readonly url: string) {
    super();
    FakeEventSource.instances.push(this);
  }

  close(): void {
    this.closed = true;
  }

  emitLog(lines: LogLine[]): void {
    this.dispatchEvent(new MessageEvent("log", { data: JSON.stringify(lines) }));
  }

  emitTick(seq = 0): void {
    this.dispatchEvent(new MessageEvent("tick", { data: JSON.stringify({ seq }) }));
  }

  static reset(): void {
    FakeEventSource.instances = [];
  }

  /** The stream the component under test just opened. */
  static latest(): FakeEventSource {
    const source = FakeEventSource.instances.at(-1);
    if (source === undefined) {
      throw new Error("No stream was opened");
    }
    return source;
  }
}
