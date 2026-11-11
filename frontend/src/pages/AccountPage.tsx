import { useMutation } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { api } from "../api/client";
import { useMe } from "../auth";
import { Section } from "../components/common";

export function AccountPage() {
  const me = useMe().data;
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [repeat, setRepeat] = useState("");
  const change = useMutation({
    mutationFn: () => api.changePassword(current, next),
    onSuccess: () => {
      setCurrent("");
      setNext("");
      setRepeat("");
    },
  });
  const mismatch = repeat.length > 0 && next !== repeat;
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!mismatch) change.mutate();
  };

  return (
    <>
      <div className="page-head">
        <h1>My account</h1>
        <p className="muted">
          Logged in as <strong>{me?.username}</strong> · role <strong>{me?.role}</strong>
        </p>
      </div>
      <Section title="Change password">
        <form className="upload-card" onSubmit={submit}>
          <div className="form-grid">
            <label htmlFor="pw-current">Current</label>
            <input id="pw-current" type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} />
            <label htmlFor="pw-new">New</label>
            <input id="pw-new" type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} />
            <label htmlFor="pw-repeat">Repeat new</label>
            <input id="pw-repeat" type="password" autoComplete="new-password" value={repeat} onChange={(e) => setRepeat(e.target.value)} />
          </div>
          <p className="muted small">At least 10 characters, not containing your user name.</p>
          {mismatch && <p className="error small">The two new passwords differ.</p>}
          {change.error && <p className="error small">{change.error.message}</p>}
          {change.isSuccess && <p className="ok-text small">Password changed.</p>}
          <div className="upload-actions">
            <span />
            <button className="btn" type="submit" disabled={!current || !next || mismatch || change.isPending}>
              Change password
            </button>
          </div>
        </form>
      </Section>
    </>
  );
}
