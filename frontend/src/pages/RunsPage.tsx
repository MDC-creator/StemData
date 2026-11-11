import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { Link } from "react-router-dom";

import { api, type SummaryRow } from "../api/client";
import { ErrorBox, External, Loading, Section } from "../components/common";
import { Plot, palette } from "../components/Plot";

function deadFractionTraces(rows: SummaryRow[]) {
  const byRun = new Map<string, SummaryRow[]>();
  rows.filter((r) => r.dead_fraction != null).forEach((r) => byRun.set(r.run_id, [...(byRun.get(r.run_id) ?? []), r]));
  return [...byRun.entries()].map(([run, rs], i) => ({
    type: "scatter",
    mode: "lines+markers",
    name: run,
    x: rs.map((r) => r.day),
    y: rs.map((r) => (r.dead_fraction ?? 0) * 100),
    text: rs.map((r) => `${r.nuclei} nuclei`),
    hovertemplate: `${run}, day %{x}: %{y:.1f} %% dead (%{text})<extra></extra>`,
    line: { color: palette[i % palette.length], width: 2 },
    marker: { size: 9 },
  }));
}

export function RunsPage() {
  const runs = useQuery({ queryKey: ["runs"], queryFn: api.runs, refetchInterval: 15_000 });
  const summary = useQuery({ queryKey: ["summary"], queryFn: api.summary, refetchInterval: 15_000 });
  const traces = useMemo(() => deadFractionTraces(summary.data ?? []), [summary.data]);

  return (
    <>
      <div className="page-head">
        <h1>Runs</h1>
        <p className="muted">
          Bioreactor runs from eLabFTW, with images and process data from Nextcloud. New files appear here automatically.
        </p>
      </div>

      {runs.isLoading && <Loading what="runs" />}
      {runs.error && <ErrorBox error={runs.error} />}
      {runs.data?.length === 0 && (
        <div className="empty">
          <h3>No runs yet</h3>
          <p>
            Put microscopy files into Nextcloud as <code>INDUZELL/&lt;run&gt;/day&lt;NN&gt;/&lt;file&gt;.czi</code> and process data as{" "}
            <code>INDUZELL/&lt;run&gt;/process.csv</code>, or create an eLabFTW experiment with the extra field <code>run_id</code>.
          </p>
        </div>
      )}

      <div className="run-grid">
        {runs.data?.map((run) => (
          <article key={run.id} className="run-card">
            <Link to={`/runs/${run.id}`} className="run-card-main">
              <div className="run-id">{run.id}</div>
              <div className="run-title">{run.title ?? "not in eLabFTW yet"}</div>
              <div className="muted small">{[run.cell_line, run.protocol].filter(Boolean).join(" · ") || "–"}</div>
              <div className="progress" title={`${run.analyzed_count} of ${run.image_count} images analysed`}>
                <div style={{ width: `${run.image_count ? (100 * run.analyzed_count) / run.image_count : 0}%` }} />
              </div>
              <div className="small">
                {run.analyzed_count}/{run.image_count} images analysed
              </div>
            </Link>
            {run.elab_url && (
              <div className="run-card-foot">
                <External href={run.elab_url}>eLabFTW #{run.elab_id}</External>
              </div>
            )}
          </article>
        ))}
      </div>

      {traces.length > 0 && (
        <Section title="Dead-cell fraction over time">
          <p className="muted small">Share of EthD-positive nuclei among all Hoechst-stained nuclei, pooled per run and day.</p>
          <Plot
            data={traces}
            layout={{
              xaxis: { title: { text: "day" }, dtick: 1 },
              // at least 0–10 %, so "no dead cells" reads as a line at zero, not as an empty chart
              yaxis: { title: { text: "dead cells (%)" }, range: [0, Math.max(10, ...traces.flatMap((t) => t.y)) * 1.1] },
            }}
          />
        </Section>
      )}
    </>
  );
}
