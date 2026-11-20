import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { PropsWithChildren } from "react";
import { BrowserRouter } from "react-router-dom";
import { Toaster } from "../components/ui/toaster";
import { NexconnSessionProvider } from "../services/nexconn-session";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

export function AppProviders({ children }: PropsWithChildren) {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <NexconnSessionProvider>
          {children}
          <Toaster />
        </NexconnSessionProvider>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
