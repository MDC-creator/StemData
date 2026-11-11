import { QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";

import { ApiError } from "./api/client";
import { AuthGate } from "./auth";
import { Layout } from "./components/Layout";
import { AccountPage } from "./pages/AccountPage";
import { ComparePage } from "./pages/ComparePage";
import { JobsPage } from "./pages/JobsPage";
import { RunPage } from "./pages/RunPage";
import { RunsPage } from "./pages/RunsPage";
import { UploadPage } from "./pages/UploadPage";
import { UsersPage } from "./pages/UsersPage";
import "./styles.css";

const queryClient: QueryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 10_000, retry: (n, err) => !(err instanceof ApiError && err.status < 500) && n < 1 } },
  // a session that ended (expired, logged out elsewhere) sends the user back to the login page
  queryCache: new QueryCache({
    onError: (err) => {
      if (err instanceof ApiError && err.status === 401) queryClient.setQueryData(["me"], null);
    },
  }),
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthGate>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<RunsPage />} />
            <Route path="runs/:runId" element={<RunPage />} />
            <Route path="upload" element={<UploadPage />} />
            <Route path="compare" element={<ComparePage />} />
            <Route path="jobs" element={<JobsPage />} />
            <Route path="account" element={<AccountPage />} />
            <Route path="users" element={<UsersPage />} />
          </Route>
        </Routes>
        </AuthGate>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
