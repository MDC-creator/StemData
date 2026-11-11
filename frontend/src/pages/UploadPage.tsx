import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { api, dayFolder, uploadForm } from "../api/client";
import { Section } from "../components/common";

const ROOT = "INDUZELL";
const RUN_RE = /^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/;

type Item = { file: File; state: "waiting" | "uploading" | "done" | "error"; progress: number; message?: string };

function RunInput({ value, onChange, id }: { value: string; onChange: (v: string) => void; id: string }) {
  const runs = useQuery({ queryKey: ["runs"], queryFn: api.runs });
  return (
    <>
      <input id={id} list={`${id}-runs`} value={value} onChange={(e) => onChange(e.target.value)} placeholder="e.g. U5" />
      <datalist id={`${id}-runs`}>
        {runs.data?.map((r) => (
          <option key={r.id} value={r.id}>
            {r.title ?? ""}
          </option>
        ))}
      </datalist>
    </>
  );
}

function ImageUpload() {
  const qc = useQueryClient();
  const [run, setRun] = useState("");
  const [day, setDay] = useState("0");
  const [replace, setReplace] = useState(false);
  const [items, setItems] = useState<Item[]>([]);
  const [busy, setBusy] = useState(false);

  const runId = run.trim().toUpperCase();
  const dayNum = Number(day);
  const runOk = RUN_RE.test(runId);
  const dayOk = Number.isInteger(dayNum) && dayNum >= -5 && dayNum <= 60;
  const folder = `${ROOT}/${runOk ? runId : "<run>"}/${dayOk ? dayFolder(dayNum) : "day<NN>"}/`;
  const notCzi = items.filter((i) => !i.file.name.toLowerCase().endsWith(".czi"));
  const ready = runOk && dayOk && items.length > 0 && notCzi.length === 0 && !busy;

  const update = (idx: number, patch: Partial<Item>) => setItems((xs) => xs.map((x, i) => (i === idx ? { ...x, ...patch } : x)));

  async function start() {
    setBusy(true);
    for (const [idx, item] of items.entries()) {
      if (item.state === "done") continue;
      update(idx, { state: "uploading", progress: 0, message: undefined });
      const form = new FormData();
      form.append("run_id", runId);
      form.append("day", String(dayNum));
      form.append("replace", String(replace));
      form.append("file", item.file);
      try {
        const res = await uploadForm("/uploads/image", form, (p) => update(idx, { progress: p }));
        update(idx, { state: "done", progress: 1, message: res.path });
      } catch (e) {
        update(idx, { state: "error", message: e instanceof Error ? e.message : String(e) });
      }
    }
    setBusy(false);
    qc.invalidateQueries({ queryKey: ["runs"] });
  }

  return (
    <div className="upload-card">
      <div className="form-grid">
        <label htmlFor="img-run">Run</label>
        <RunInput id="img-run" value={run} onChange={setRun} />
        <label htmlFor="img-day">Day</label>
        <input id="img-day" type="number" min={-5} max={60} value={day} onChange={(e) => setDay(e.target.value)} />
        <label htmlFor="img-files">Images</label>
        <input
          id="img-files"
          type="file"
          accept=".czi"
          multiple
          onChange={(e) => setItems([...(e.target.files ?? [])].map((file) => ({ file, state: "waiting", progress: 0 })))}
        />
      </div>

      <p className="path-preview">
        will be saved to <code>{folder}</code>
        {!runOk && run && <span className="error"> · run: letters, digits, - or _</span>}
        {!dayOk && <span className="error"> · day must be between -5 and 60</span>}
      </p>
      {notCzi.length > 0 && <p className="error">Only .czi files: {notCzi.map((i) => i.file.name).join(", ")}</p>}

      {items.length > 0 && (
        <ul className="upload-list">
          {items.map((it, idx) => (
            <li key={`${it.file.name}-${idx}`} className={`upload-${it.state}`}>
              <span className="upload-name">{it.file.name}</span>
              <span className="muted small">{(it.file.size / 1e6).toFixed(1)} MB</span>
              {it.state === "uploading" && (
                <span className="progress inline">
                  <span style={{ width: `${Math.round(it.progress * 100)}%` }} />
                </span>
              )}
              <span className={it.state === "error" ? "error small" : "muted small"}>
                {it.state === "done" ? "✓ uploaded — analysis starts now" : it.state === "error" ? it.message : it.state === "uploading" ? `${Math.round(it.progress * 100)} %` : ""}
              </span>
            </li>
          ))}
        </ul>
      )}

      <div className="upload-actions">
        <label className="small">
          <input type="checkbox" checked={replace} onChange={(e) => setReplace(e.target.checked)} /> replace files that already exist
        </label>
        <button className="btn" onClick={start} disabled={!ready}>
          {busy ? "Uploading…" : `Upload ${items.length || ""} file${items.length === 1 ? "" : "s"}`}
        </button>
      </div>
      {items.some((i) => i.state === "done") && runOk && (
        <p className="small">
          Follow the import on <Link to="/jobs">Activity</Link> or open <Link to={`/runs/${runId}`}>run {runId}</Link>.
        </p>
      )}
    </div>
  );
}

function ProcessUpload() {
  const qc = useQueryClient();
  const [run, setRun] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const runId = run.trim().toUpperCase();
  const ready = RUN_RE.test(runId) && file !== null && !busy;

  async function start() {
    if (!file) return;
    setBusy(true);
    setResult(null);
    const form = new FormData();
    form.append("run_id", runId);
    form.append("file", file);
    try {
      const res = await uploadForm("/uploads/process", form);
      setResult({ ok: true, text: `${res.message} → ${res.path}` });
      qc.invalidateQueries();
    } catch (e) {
      setResult({ ok: false, text: e instanceof Error ? e.message : String(e) });
    }
    setBusy(false);
  }

  return (
    <div className="upload-card">
      <div className="form-grid">
        <label htmlFor="csv-run">Run</label>
        <RunInput id="csv-run" value={run} onChange={setRun} />
        <label htmlFor="csv-file">CSV file</label>
        <input id="csv-file" type="file" accept=".csv,text/csv" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
      </div>
      <p className="path-preview">
        will be saved to <code>{`${ROOT}/${RUN_RE.test(runId) ? runId : "<run>"}/process.csv`}</code> (replaces the run's previous table)
      </p>
      <p className="muted small">
        Columns <code>day, parameter, value, unit</code> — one value per row; comma or semicolon, decimal point or comma. The file is checked before it
        is uploaded.
      </p>
      {result && <p className={result.ok ? "ok-text" : "error"}>{result.text}</p>}
      <div className="upload-actions">
        <span />
        <button className="btn" onClick={start} disabled={!ready}>
          {busy ? "Uploading…" : "Upload process data"}
        </button>
      </div>
    </div>
  );
}

export function UploadPage() {
  return (
    <>
      <div className="page-head">
        <h1>Upload</h1>
        <p className="muted">
          Choose the run and the day; the file is saved in Nextcloud under the right folder, then imported into OMERO and analysed automatically.
        </p>
      </div>
      <Section title="Microscopy images (.czi)">
        <ImageUpload />
      </Section>
      <Section title="Process data (process.csv)">
        <ProcessUpload />
      </Section>
    </>
  );
}
