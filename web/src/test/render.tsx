/**
 * The wrapper every screen test renders through.
 *
 * `retry: false` and `gcTime: 0` because a test that retries a deliberate
 * 404 three times spends seconds proving nothing, and a cache that outlives
 * a test leaks one test's fixtures into the next.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement, ReactNode } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

function newClient(): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
}

interface Options {
  /** The URL to start at. Defaults to "/". */
  route?: string;
  /** The route pattern `ui` is mounted at, when it reads path params. */
  path?: string;
}

export function renderWithProviders(ui: ReactElement, options: Options = {}) {
  const { route = "/", path } = options;
  return render(
    <QueryClientProvider client={newClient()}>
      <MemoryRouter initialEntries={[route]}>
        {path === undefined ? ui : <Routes>{<Route path={path} element={ui} />}</Routes>}
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/** The `wrapper` form, for `renderHook`. */
renderWithProviders.Wrapper = function Wrapper({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={newClient()}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  );
};
