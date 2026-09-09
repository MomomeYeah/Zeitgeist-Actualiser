import { setupServer } from "msw/node";

/**
 * No default handlers.
 *
 * Every test declares the responses its screen needs with `server.use`, so
 * a test that forgot one fails loudly on an unhandled request rather than
 * quietly passing against a fixture it did not choose.
 */
export const server = setupServer();
