import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { BrowserRouter } from "react-router-dom";

/**
 * `retry: false` for the same reason the test harness sets it: every failure
 * these screens can produce is either a 404 (retrying cannot help) or a
 * server that is down (the user can see that faster than three backoffs
 * can). `refetchOnWindowFocus` stays on — coming back to a tab after a run
 * finished elsewhere should show the run that finished.
 */
const client = new QueryClient({
  defaultOptions: { queries: { retry: false, staleTime: 30_000 } },
});

export function Providers({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={client}>
      <BrowserRouter>{children}</BrowserRouter>
    </QueryClientProvider>
  );
}
