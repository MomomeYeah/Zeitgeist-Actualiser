import "@testing-library/jest-dom/vitest";

import { afterAll, afterEach, beforeAll, beforeEach } from "vitest";

import { setEventSourceFactory } from "@/api/client";
import { FakeEventSource } from "@/test/eventsource";
import { server } from "@/test/server";

// `error` rather than `warn`: an unhandled request means a screen asked for
// something the test did not describe, and the assertion that follows would
// fail for a reason that has nothing to do with what is being tested.
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

// Installed for every test, not only the ones that assert on a stream: a
// screen that opens one in an effect must not reach the network because
// the test did not think to stub it.
beforeEach(() => {
  FakeEventSource.reset();
  setEventSourceFactory((url) => new FakeEventSource(url));
});
