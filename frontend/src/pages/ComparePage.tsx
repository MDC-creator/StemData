import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import { ErrorBox, Loading, Section, num, pct } from "../components/common";
import { Plot, palette } from "../components/Plot";

type Op = ">" | "<";

export function ComparePage() {
  const summary = useQuery({ queryKey: ["summary"], queryFn: api.summary });
  const rows = useMemo(() => summary.data ?? [], [summary.data]);
  const params = useMemo(() => [...new Set(rows.flatMap((r) => Object.keys(r.process)))].sort(), [rows]);

  const [param, setParam] = useState("");
  const [op, setOp] = useState<Op>(">");
  const [threshold, setThreshold] = useState("");
  const [onlyImaged, setOnlyImaged] = useState(true);
  const active = param || params[0] || "";

  const limit = threshold.trim() === "" ? null : Number(threshold.replace(",", "."));
  const matches = (v: number | undefined) => v != null && (limit == null || Number.isNaN(limit) || (op === ">" ? v > limit : v < limit));

  const candidates = rows.filter((r) => (!onlyImaged || r.dead_fraction != null) && r.process[active] != null);
  const hits = candidates.filter((r) => matches(r.process[active]));

  const runs = [...new Set(candidates.map((r) => r.run_id))];
  const traces = runs.map((run, i) => {
    const rs = candidates.filter((r) => r.run_id === run && r.dead_fraction != null);
    return {
      type: "scatter",
      mode: "markers+text",
      name: run,
      x: rs.map((r) => r.process[active]),
      y: rs.map((r) => (r.dead_fraction ?? 0) * 100),
      text: rs.map((r) => `d${r.day}`),
      textposition: "top center",
      marker: {
        size: rs.map((r) => (matches(r.process[active]) ? 14 : 8)),
        color: palette[i % palette.length],
        line: { width: rs.map((r) => (matches(r.process[active]) ? 2 : 0)), color: "#1f2328" },
      },
      hovertemplate: `${run}, %{text}: ${active} %{x}, %{y:.1f} %% dead<extra></extra>`,
    };
  });

  if (summary.isLoading) return <Loading what="data" />;
  if (summary.error) return <ErrorBox error={summary.error} />;

  return (
    <>
      <div className="page-head">
        <h1>Compare runs</h1>
        <p className="muted">Ask a question across all runs: which days had a given process condition, and how did the cells look?</p>
      </div>

      <div className="question">
        <span>Show run-days where</span>
        <select value={active} onChange={(e) => setParam(e.target.value)} aria-label="process parameter">
          {params.map((p) => (
            <option key={p}>{p}</option>
          ))}
        </select>
        <select value={op} onChange={(e) => setOp(e.target.value as Op)} aria-label="comparison">
          <option value=">">is above</option>
          <option value="<">is below</option>
        </select>
        <input value={threshold} onChange={(e) => setThreshold(e.target.value)} placeholder="any value" inputMode="decimal" aria-label="threshold" />
        <label className="small">
          <input type="checkbox" checked={onlyImaged} onChange={(e) => setOnlyImaged(e.target.checked)} /> only days with analysed images
        </label>
      </div>
      <p className="answer">
        <strong>{hits.length}</strong> of {candidates.length} run-days match.
      </p>

      <Section title={`Dead-cell fraction vs. ${active}`}>
        {traces.some((t) => t.x.length) ? (
          <Plot
            data={traces}
            height={320}
            layout={{
              xaxis: { title: { text: active } },
              yaxis: { title: { text: "dead cells (%)" }, range: [0, Math.max(10, ...traces.flatMap((t) => t.y)) * 1.1] },
              shapes:
                limit != null && !Number.isNaN(limit)
                  ? [{ type: "line", x0: limit, x1: limit, yref: "paper", y0: 0, y1: 1, line: { dash: "dash", color: "#555" } }]
                  : [],
            }}
          />
        ) : (
          <p className="muted">No analysed images with process data yet.</p>
        )}
      </Section>

      <Section title="Matching run-days">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Run</th>
                <th>Day</th>
                <th>{active}</th>
                <th>Images</th>
                <th>Nuclei</th>
                <th>Dead</th>
                <th>Nucleus area (µm²)</th>
              </tr>
            </thead>
            <tbody>
              {hits.map((r) => (
                <tr key={`${r.run_id}-${r.day}`}>
                  <td>
                    <Link to={`/runs/${r.run_id}`}>{r.run_id}</Link>
                  </td>
                  <td>{r.day}</td>
                  <td>{r.process[active]}</td>
                  <td>{r.images}</td>
                  <td>{r.images ? r.nuclei : "–"}</td>
                  <td>{pct(r.dead_fraction)}</td>
                  <td>{num(r.mean_nucleus_area_um2, 1)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>
    </>
  );
}
