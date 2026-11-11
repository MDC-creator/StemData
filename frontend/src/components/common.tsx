import type { ReactNode } from "react";

export const pct = (v: number | null | undefined, digits = 1) => (v == null ? "–" : `${(v * 100).toFixed(digits)} %`);
export const num = (v: number | null | undefined, digits = 0) => (v == null ? "–" : v.toFixed(digits));
export const dayLabel = (d: number) => `day ${d}`;

export function StatusBadge({ status }: { status: string }) {
  return <span className={`badge badge-${status}`}>{status}</span>;
}

export function Section({ title, children, aside }: { title: string; children: ReactNode; aside?: ReactNode }) {
  return (
    <section className="section">
      <div className="section-head">
        <h2>{title}</h2>
        {aside}
      </div>
      {children}
    </section>
  );
}

export function External({ href, children }: { href: string; children: ReactNode }) {
  return (
    <a href={href} target="_blank" rel="noreferrer" className="ext">
      {children} ↗
    </a>
  );
}

export function Loading({ what }: { what: string }) {
  return <p className="muted">Loading {what}…</p>;
}

export function ErrorBox({ error }: { error: unknown }) {
  return <p className="error">Could not load: {error instanceof Error ? error.message : String(error)}</p>;
}
