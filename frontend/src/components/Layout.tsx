import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { NavLink, Outlet } from "react-router-dom";

import { api, can } from "../api/client";
import { useLogout, useMe } from "../auth";

function ServiceStatus() {
  const { data, isError } = useQuery({ queryKey: ["health"], queryFn: api.health, refetchInterval: 30_000 });
  if (isError) return <span className="status-dot bad" title="API not reachable" />;
  return (
    <div className="services" aria-label="Service status">
      {data?.services.map((s) => (
        <span key={s.name} className="service" title={s.detail}>
          <span className={`status-dot ${s.ok ? "ok" : "bad"}`} />
          {s.name}
        </span>
      ))}
    </div>
  );
}

function SyncButton() {
  const qc = useQueryClient();
  const sync = useMutation({
    mutationFn: api.sync,
    onSuccess: () => setTimeout(() => qc.invalidateQueries(), 3000),
  });
  return (
    <button className="btn" onClick={() => sync.mutate()} disabled={sync.isPending} title="Check Nextcloud and eLabFTW now">
      {sync.isPending ? "Syncing…" : sync.isSuccess ? "Sync started ✓" : "Sync now"}
    </button>
  );
}

export function Layout() {
  const me = useMe().data ?? undefined;
  const logout = useLogout();
  return (
    <>
      <header className="topbar">
        <NavLink to="/" className="brand">
          StemC<span>DataHub</span>
        </NavLink>
        <nav>
          <NavLink to="/" end>
            Runs
          </NavLink>
          {can(me, "scientist") && <NavLink to="/upload">Upload</NavLink>}
          <NavLink to="/compare">Compare</NavLink>
          <NavLink to="/jobs">Activity</NavLink>
          {can(me, "admin") && <NavLink to="/users">Users</NavLink>}
        </nav>
        <div className="topbar-right">
          <ServiceStatus />
          {can(me, "scientist") && <SyncButton />}
          <div className="user-menu">
            <NavLink to="/account" title="My account">
              {me?.username} <span className="muted small">· {me?.role}</span>
            </NavLink>
            <button className="btn btn-quiet btn-small" onClick={() => logout.mutate()}>
              Log out
            </button>
          </div>
        </div>
      </header>
      <main className="page">
        <Outlet />
      </main>
    </>
  );
}
