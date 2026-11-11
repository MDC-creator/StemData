import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api, can, imageUrls, type ImageItem, type Measurement, type SummaryRow } from "../api/client";
import { useMe } from "../auth";
import { ErrorBox, External, Loading, Section, StatusBadge, num, pct } from "../components/common";
import { Plot, palette } from "../components/Plot";

const PENDING = new Set(["new", "queued", "importing", "analyzing"]);

// ---------------------------------------------------------------- process data

function ProcessCharts({ measurements, imageDays }: { measurements: Measurement[]; imageDays: number[] }) {
  const params = useMemo(() => {
    const m = new Map<string, Measurement[]>();
    measurements.forEach((x) => m.set(x.parameter, [...(m.get(x.parameter) ?? []), x]));
    return [...m.entries()];
  }, [measurements]);

  if (params.length === 0)
    return (
      <p className="muted">
        No process data. Upload <code>process.csv</code> (columns day, parameter, value, unit) into the run's Nextcloud folder.
      </p>
    );

  // dotted lines on days with microscopy images, so curves and images can be related
  const shapes = imageDays.map((d) => ({
    type: "line",
    x0: d,
    x1: d,
    yref: "paper",
    y0: 0,
    y1: 1,
    line: { color: "#b4532a", width: 1, dash: "dot" },
  }));

  return (
    <div className="chart-grid">
      {params.map(([name, rows], i) => {
        const unit = rows.find((r) => r.unit)?.unit;
        return (
          <div key={name} className="chart-card">
            <div className="chart-title">
              {name} {unit && <span className="muted">({unit})</span>}
            </div>
            <Plot
              height={200}
              data={[
                {
                  type: "scatter",
                  mode: "lines+markers",
                  x: rows.map((r) => r.day),
                  y: rows.map((r) => r.value),
                  line: { color: palette[i % palette.length], width: 2 },
                  marker: { size: 5 },
                  hovertemplate: `day %{x}: %{y} ${unit ?? ""}<extra></extra>`,
                },
              ]}
              layout={{ margin: { l: 44, r: 8, t: 8, b: 32 }, shapes, xaxis: { dtick: 2 }, showlegend: false }}
            />
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------- images

function ImageCard({ img, selected, onSelect }: { img: ImageItem; selected: boolean; onSelect: () => void }) {
  const r = img.result;
  return (
    <button className={`image-card ${selected ? "selected" : ""}`} onClick={onSelect}>
      <div className="thumb">
        {img.omero_image_id ? <img src={imageUrls(img.id).thumbnail} alt={img.filename} loading="lazy" /> : <span>not in OMERO yet</span>}
        <span className="thumb-day">day {img.day}</span>
      </div>
      <div className="image-card-body">
        <div className="image-card-name" title={img.filename}>
          {img.filename}
        </div>
        <StatusBadge status={img.status} />
        {r && (
          <div className="kv">
            <span>{r.nuclei_count} nuclei</span>
            <span className="dead">{pct(r.dead_fraction)} dead</span>
          </div>
        )}
      </div>
    </button>
  );
}

function ImageDetail({ img }: { img: ImageItem }) {
  const me = useMe().data ?? undefined;
  const [overlay, setOverlay] = useState(true);
  const qc = useQueryClient();
  const nuclei = useQuery({ queryKey: ["nuclei", img.id], queryFn: () => api.nuclei(img.id), enabled: img.status === "done" });
  const reprocess = useMutation({
    mutationFn: () => api.reprocess(img.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["images"] }),
  });
  const r = img.result;
  const urls = imageUrls(img.id);

  const alive = nuclei.data?.filter((n) => !n.dead) ?? [];
  const dead = nuclei.data?.filter((n) => n.dead) ?? [];

  return (
    <div className="detail">
      <div className="viewer">
        {img.omero_image_id ? (
          <div className="viewer-stack">
            <img src={urls.preview} alt={`${img.filename}, maximum projection`} />
            {overlay && img.status === "done" && <img src={`${urls.mask}?v=${r?.analyzed_at}`} alt="" className="overlay" />}
          </div>
        ) : (
          <div className="viewer-empty">Image is being imported into OMERO…</div>
        )}
        <div className="viewer-bar">
          <label>
            <input type="checkbox" checked={overlay} onChange={(e) => setOverlay(e.target.checked)} /> nucleus outlines
            <span className="legend-alive">alive</span>
            <span className="legend-dead">dead</span>
          </label>
          <span className="muted small">max. projection of {img.size_z ?? "?"} z-planes</span>
        </div>
      </div>

      <div className="detail-side">
        <h3>
          Day {img.day} · {img.filename}
        </h3>
        <div className="links">
          {img.omero_url && <External href={img.omero_url}>Open in OMERO</External>}
          <span className="muted small" title={img.nextcloud_path}>
            Nextcloud: {img.nextcloud_path}
          </span>
        </div>
        {img.error && <p className="error">{img.error}</p>}
        {r ? (
          <dl className="stats">
            <dt>Nuclei</dt>
            <dd>{r.nuclei_count}</dd>
            <dt>Dead (EthD+)</dt>
            <dd>
              {r.dead_count} · {pct(r.dead_fraction)}
            </dd>
            <dt>Mean nucleus area</dt>
            <dd>{num(r.mean_nucleus_area_um2, 1)} µm²</dd>
            <dt>Aggregate area</dt>
            <dd>{num((r.aggregate_area_um2 ?? 0) / 1000, 1)} ×10³ µm²</dd>
            <dt>Channels</dt>
            <dd>{img.channels?.join(", ")}</dd>
            <dt>Pixel size</dt>
            <dd>{num(img.pixel_size_um, 3)} µm</dd>
            <dt>Method</dt>
            <dd>{r.segmenter}</dd>
          </dl>
        ) : (
          <p className="muted">{PENDING.has(img.status) ? "Analysis running…" : "No results."}</p>
        )}
        {can(me, "scientist") && (
          <button className="btn btn-quiet" onClick={() => reprocess.mutate()} disabled={reprocess.isPending || PENDING.has(img.status)}>
            Re-run analysis
          </button>
        )}
      </div>

      {nuclei.data && nuclei.data.length > 0 && (
        <div className="detail-charts">
          <div className="chart-card">
            <div className="chart-title">Nucleus area</div>
            <Plot
              height={220}
              data={[
                { type: "histogram", x: alive.map((n) => n.area_um2), name: "alive", marker: { color: "#3cb878" }, opacity: 0.75 },
                { type: "histogram", x: dead.map((n) => n.area_um2), name: "dead", marker: { color: "#d63cb4" }, opacity: 0.75 },
              ]}
              layout={{ barmode: "overlay", xaxis: { title: { text: "µm²" } }, yaxis: { title: { text: "nuclei" } } }}
            />
          </div>
          <div className="chart-card">
            <div className="chart-title">Why a nucleus counts as dead</div>
            <Plot
              height={220}
              data={[
                {
                  type: "scattergl",
                  mode: "markers",
                  name: "alive",
                  x: alive.map((n) => n.hoechst_mean),
                  y: alive.map((n) => n.ethd_mean),
                  marker: { color: "#3cb878", size: 5 },
                },
                {
                  type: "scattergl",
                  mode: "markers",
                  name: "dead",
                  x: dead.map((n) => n.hoechst_mean),
                  y: dead.map((n) => n.ethd_mean),
                  marker: { color: "#d63cb4", size: 5 },
                },
              ]}
              layout={{
                xaxis: { title: { text: "Hoechst intensity" } },
                yaxis: { title: { text: "EthD intensity" } },
                shapes: r?.ethd_threshold
                  ? [{ type: "line", xref: "paper", x0: 0, x1: 1, y0: r.ethd_threshold, y1: r.ethd_threshold, line: { dash: "dash", color: "#555" } }]
                  : [],
              }}
            />
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- day table

function DayTable({ rows }: { rows: SummaryRow[] }) {
  const params = [...new Set(rows.flatMap((r) => Object.keys(r.process)))].sort();
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Day</th>
            <th>Images</th>
            <th>Nuclei</th>
            <th>Dead</th>
            <th>Nucleus area (µm²)</th>
            {params.map((p) => (
              <th key={p}>{p}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.day} className={r.images ? "has-images" : ""}>
              <td>{r.day}</td>
              <td>{r.images || ""}</td>
              <td>{r.images ? r.nuclei : ""}</td>
              <td>{pct(r.dead_fraction)}</td>
              <td>{num(r.mean_nucleus_area_um2, 1)}</td>
              {params.map((p) => (
                <td key={p}>{r.process[p] ?? "–"}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------- page

export function RunPage() {
  const { runId = "" } = useParams();
  const run = useQuery({ queryKey: ["run", runId], queryFn: () => api.run(runId) });
  const measurements = useQuery({ queryKey: ["measurements", runId], queryFn: () => api.measurements(runId) });
  const images = useQuery({
    queryKey: ["images", runId],
    queryFn: () => api.images(runId),
    refetchInterval: (q) => (q.state.data?.some((i) => PENDING.has(i.status)) ? 4000 : false),
  });
  const summary = useQuery({ queryKey: ["summary"], queryFn: api.summary });
  const [selected, setSelected] = useState<number | null>(null);

  useEffect(() => {
    if (selected == null && images.data?.length) setSelected(images.data[0].id);
  }, [images.data, selected]);

  if (run.isLoading) return <Loading what="run" />;
  if (run.error) return <ErrorBox error={run.error} />;
  const r = run.data!;
  const imageDays = [...new Set(images.data?.map((i) => i.day) ?? [])];
  const selectedImage = images.data?.find((i) => i.id === selected);

  return (
    <>
      <div className="page-head">
        <Link to="/" className="muted small">
          ← all runs
        </Link>
        <h1>
          {r.id} <span className="h1-sub">{r.title}</span>
        </h1>
        <div className="chips">
          {r.cell_line && <span className="chip">cell line: {r.cell_line}</span>}
          {r.protocol && <span className="chip">protocol: {r.protocol}</span>}
          {r.status && <span className="chip">eLabFTW status: {r.status}</span>}
          {r.elab_url ? <External href={r.elab_url}>eLabFTW entry #{r.elab_id}</External> : <span className="muted small">no eLabFTW entry</span>}
        </div>
      </div>

      <Section title="Process data" aside={<span className="muted small legend-days">┊ days with microscopy images</span>}>
        {measurements.data ? <ProcessCharts measurements={measurements.data} imageDays={imageDays} /> : <Loading what="process data" />}
      </Section>

      <Section title="Microscopy">
        {images.data?.length === 0 && <p className="muted">No images yet for this run.</p>}
        <div className="image-strip">
          {images.data?.map((img) => (
            <ImageCard key={img.id} img={img} selected={img.id === selected} onSelect={() => setSelected(img.id)} />
          ))}
        </div>
        {selectedImage && <ImageDetail key={selectedImage.id} img={selectedImage} />}
      </Section>

      <Section title="Day by day">
        <p className="muted small">Image results next to that day's process values — the combined view no single tool gives.</p>
        <DayTable rows={(summary.data ?? []).filter((s) => s.run_id === r.id)} />
      </Section>
    </>
  );
}
