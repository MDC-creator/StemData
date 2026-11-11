import { useQuery } from "@tanstack/react-query";

import { api } from "../api/client";
import { ErrorBox, Loading, StatusBadge } from "../components/common";

const time = (iso: string | null | undefined) => (iso ? new Date(iso).toLocaleString() : "–");
const duration = (a: string, b: string | null | undefined) => (b ? `${((Date.parse(b) - Date.parse(a)) / 1000).toFixed(1)} s` : "…");

export function JobsPage() {
  const jobs = useQuery({ queryKey: ["jobs"], queryFn: api.jobs, refetchInterval: 4000 });
  return (
    <>
      <div className="page-head">
        <h1>Activity</h1>
        <p className="muted">
          What the background worker did: checking Nextcloud for new files, syncing eLabFTW, importing into OMERO and analysing images.
        </p>
      </div>
      {jobs.isLoading && <Loading what="activity" />}
      {jobs.error && <ErrorBox error={jobs.error} />}
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>#</th>
              <th>Task</th>
              <th>Status</th>
              <th>Started</th>
              <th>Took</th>
              <th>Result</th>
            </tr>
          </thead>
          <tbody>
            {jobs.data?.map((j) => (
              <tr key={j.id}>
                <td>{j.id}</td>
                <td>
                  <code>{j.kind}</code>
                </td>
                <td>
                  <StatusBadge status={j.status} />
                </td>
                <td>{time(j.created_at)}</td>
                <td>{duration(j.created_at, j.finished_at)}</td>
                <td className={j.status === "error" ? "error" : ""}>{j.message}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
