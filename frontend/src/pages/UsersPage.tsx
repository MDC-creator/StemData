import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { api, type User } from "../api/client";
import { useMe } from "../auth";
import { ErrorBox, Loading, Section } from "../components/common";

const ROLES = ["viewer", "scientist", "admin"] as const;
const ROLE_HELP = "viewer: look · scientist: also upload and re-run analysis · admin: also manage users";

function NewUser() {
  const qc = useQueryClient();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("scientist");
  const create = useMutation({
    mutationFn: () => api.createUser(username, password, role),
    onSuccess: () => {
      setUsername("");
      setPassword("");
      qc.invalidateQueries({ queryKey: ["users"] });
    },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    create.mutate();
  };
  return (
    <form className="upload-card" onSubmit={submit}>
      <div className="form-grid">
        <label htmlFor="nu-name">User name</label>
        <input id="nu-name" value={username} onChange={(e) => setUsername(e.target.value)} placeholder="e.g. emma" />
        <label htmlFor="nu-pass">Password</label>
        <input id="nu-pass" type="text" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="at least 10 characters" />
        <label htmlFor="nu-role">Role</label>
        <select id="nu-role" value={role} onChange={(e) => setRole(e.target.value)}>
          {ROLES.map((r) => (
            <option key={r}>{r}</option>
          ))}
        </select>
      </div>
      <p className="muted small">{ROLE_HELP}. Give the password to the person; they can change it under “My account”.</p>
      {create.error && <p className="error small">{create.error.message}</p>}
      {create.isSuccess && <p className="ok-text small">User created.</p>}
      <div className="upload-actions">
        <span />
        <button className="btn" type="submit" disabled={!username || !password || create.isPending}>
          Create user
        </button>
      </div>
    </form>
  );
}

function UserRow({ user, isMe }: { user: User; isMe: boolean }) {
  const qc = useQueryClient();
  const update = useMutation({
    mutationFn: (patch: { role?: string; active?: boolean; password?: string }) => api.updateUser(user.id, patch),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["users"] }),
  });
  const resetPassword = () => {
    const pw = window.prompt(`New password for ${user.username} (at least 10 characters):`);
    if (pw) update.mutate({ password: pw });
  };
  return (
    <tr className={user.active ? "" : "inactive"}>
      <td>
        {user.username} {isMe && <span className="muted small">(you)</span>}
      </td>
      <td>
        <select value={user.role} disabled={isMe || update.isPending} onChange={(e) => update.mutate({ role: e.target.value })}>
          {ROLES.map((r) => (
            <option key={r}>{r}</option>
          ))}
        </select>
      </td>
      <td>{user.active ? "active" : "deactivated"}</td>
      <td>{user.last_login ? new Date(user.last_login).toLocaleString() : "never"}</td>
      <td className="row-actions">
        <button className="btn btn-quiet btn-small" onClick={resetPassword} disabled={update.isPending}>
          Reset password
        </button>
        {!isMe && (
          <button className="btn btn-quiet btn-small" onClick={() => update.mutate({ active: !user.active })} disabled={update.isPending}>
            {user.active ? "Deactivate" : "Activate"}
          </button>
        )}
        {update.error && <span className="error small"> {update.error.message}</span>}
      </td>
    </tr>
  );
}

export function UsersPage() {
  const me = useMe().data;
  const users = useQuery({ queryKey: ["users"], queryFn: api.users });
  return (
    <>
      <div className="page-head">
        <h1>Users</h1>
        <p className="muted">Who can log in to StemCDataHub. {ROLE_HELP}.</p>
      </div>
      <Section title="Add a user">
        <NewUser />
      </Section>
      <Section title="All users">
        {users.isLoading && <Loading what="users" />}
        {users.error && <ErrorBox error={users.error} />}
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>User</th>
                <th>Role</th>
                <th>Status</th>
                <th>Last login</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {users.data?.map((u) => (
                <UserRow key={u.id} user={u} isMe={u.id === me?.id} />
              ))}
            </tbody>
          </table>
        </div>
      </Section>
    </>
  );
}
