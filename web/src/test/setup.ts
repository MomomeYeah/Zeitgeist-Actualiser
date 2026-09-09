import "@testing-library/jest-dom/vitest";

import { afterAll, afterEach, beforeAll } from "vitest";

import { server } from "@/test/server";

// `error` rather than `warn`: an unhandled request means a screen asked for
// something the test did not describe, and the assertion that follows would
// fail for a reason that has nothing to do with what is being tested.
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());
