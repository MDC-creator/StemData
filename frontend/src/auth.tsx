import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent, type ReactNode } from "react";

import { api, ApiError } from "./api/client";

/** The logged-in user (undefined while loading, null when nobody is logged in). */
export function useMe() {
  const q = useQuery({
    queryKey: ["me"],
    queryFn: async () => {
      try {
        return await api.me();
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) return null;
        throw e;
      }
    },
    retry: false,
    staleTime: 60_000,
  });
  return q;
}

function LoginPage() {
  const qc = useQueryClient();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const login = useMutation({
    mutationFn: () => api.login(username, password),
    onSuccess: (user) => {
      // keep the "me" query (the gate is subscribed to it); drop everything cached for a previous user
      qc.removeQueries({ predicate: (q) => q.queryKey[0] !== "me" });
      qc.setQueryData(["me"], user);
    },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    login.mutate();
  };
  return (
    <div className="login-wrap">
      <form className="login-card" onSubmit={submit}>
        <div className="brand login-brand">
          StemC<span>DataHub</span>
        </div>
        <p className="muted small">INDUZELL · images, runs and results in one place</p>
        <label htmlFor="login-user">User name</label>
        <input id="login-user" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} autoFocus />
        <label htmlFor="login-pass">Password</label>
        <input
          id="login-pass"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        {login.error && <p className="error small">{login.error.message}</p>}
        <button className="btn" type="submit" disabled={login.isPending || !username || !password}>
          {login.isPending ? "Logging in…" : "Log in"}
        </button>
        <p className="muted small">No account yet? Ask your StemCDataHub admin.</p>
      </form>
    </div>
  );
}

/** Shows the login page until someone is logged in. */
export function AuthGate({ children }: { children: ReactNode }) {
  const me = useMe();
  if (me.isLoading) return <p className="muted page">Loading…</p>;
  if (me.error) return <p className="error page">The API is not reachable: {me.error.message}</p>;
  if (!me.data) return <LoginPage />;
  return <>{children}</>;
}

export function useLogout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.logout,
    onSettled: () => {
      qc.setQueryData(["me"], null);
      qc.removeQueries({ predicate: (q) => q.queryKey[0] !== "me" });
    },
  });
}
