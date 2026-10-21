import { useState } from "react";
import { Badge, ConfirmDialog, ErrorNote, Loading, Notice, PageHeader, Panel, Table } from "../components/ui";
import { useAuth } from "../context/AuthContext";
import { Users } from "../lib/endpoints";
import { dateTime, timeAgo } from "../lib/format";
import { useAction, useApi } from "../lib/hooks";

const ROLES = [
  ["user", "User", "Makes predictions, sends live events and sees only their own records and notifications."],
  ["analyst", "Analyst", "Everything a user can do, plus drift investigation, performance, the model registry, data operations, simulation and system monitoring."],
  ["admin", "Admin", "Everything, plus rollback and activation, uploads, detector changes, retraining, the audit log and user management."],
];

export default function UsersPage() {
  const { user: me } = useAuth();
  const users = useApi(() => Users.list(), []);
  const update = useAction((id, body) => Users.update(id, body));
  const [confirm, setConfirm] = useState(null);       // {user, change}
  const [saved, setSaved] = useState(null);

  const apply = async (u, change) => {
    const updated = await update.run(u.id, change);
    if (updated) {
      users.setData((list) => list.map((x) => (x.id === u.id ? updated : x)));
      setSaved(`${updated.name}: ${change.role ? `role changed to ${change.role}` : updated.is_active ? "account enabled" : "account disabled and signed out everywhere"}.`);
    }
    setConfirm(null);
  };

  return (
    <>
      <PageHeader title="Users" lede="Roles decide what each person can open and do. The server enforces them on every request; changing a role takes effect on the user's next request." />
      <ErrorNote error={users.error || update.error} onRetry={users.error ? () => users.reload() : undefined} className="mb-6" />
      {saved && <Notice tone="stable" className="mb-6">{saved}</Notice>}
      <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,2.2fr)_minmax(0,1fr)]">
        <Panel flush>
          {users.loading && !users.data ? <Loading label="Loading users…" rows={4} className="px-5" /> : (
            <Table caption="Users">
              <thead><tr><th className="th">Name</th><th className="th">Email</th><th className="th">Role</th><th className="th">Account</th><th className="th">Last sign-in</th><th className="th">Joined</th></tr></thead>
              <tbody>
                {(users.data || []).map((u) => {
                  const self = u.id === me?.id;
                  return (
                    <tr key={u.id}>
                      <td className="td font-medium">{u.name}{self && <Badge tone="plum" className="ml-2">You</Badge>}</td>
                      <td className="td whitespace-nowrap text-muted">{u.email}</td>
                      <td className="td">
                        <select className="input input-sm w-auto" value={u.role} disabled={self || update.busy} aria-label={`Role for ${u.name}`}
                          onChange={(e) => setConfirm({ user: u, change: { role: e.target.value } })}>
                          {ROLES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                        </select>
                      </td>
                      <td className="td">
                        <span className="inline-flex items-center gap-2">
                          {u.is_active ? <Badge tone="stable" icon>Active</Badge> : <Badge tone="drift" icon>Disabled</Badge>}
                          {!self && <button type="button" className="link text-sm" disabled={update.busy}
                            onClick={() => setConfirm({ user: u, change: { is_active: !u.is_active } })}>{u.is_active ? "Disable" : "Enable"}</button>}
                        </span>
                      </td>
                      <td className="td whitespace-nowrap text-muted" title={dateTime(u.last_login_at)}>{u.last_login_at ? timeAgo(u.last_login_at) : "Never"}</td>
                      <td className="td whitespace-nowrap text-muted" title={dateTime(u.created_at)}>{new Date(u.created_at).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" })}</td>
                    </tr>
                  );
                })}
              </tbody>
            </Table>
          )}
          <p className="border-t border-seam px-5 py-3 text-xs text-muted">You cannot change your own role or disable your own account, so there is always an administrator.</p>
        </Panel>
        <Panel title="Roles">
          <dl className="space-y-3 text-sm">
            {ROLES.map(([v, l, text]) => <div key={v}><dt className="font-medium text-fg">{l}</dt><dd className="text-muted">{text}</dd></div>)}
          </dl>
        </Panel>
      </div>
      {confirm && (
        <ConfirmDialog open danger={confirm.change.is_active === false || confirm.change.role === "admin"} busy={update.busy}
          title={confirm.change.role ? `Make ${confirm.user.name} ${confirm.change.role === "admin" ? "an admin" : `an ${confirm.change.role}`}?`.replace("an user", "a user")
            : confirm.change.is_active ? `Enable ${confirm.user.name}'s account?` : `Disable ${confirm.user.name}'s account?`}
          confirmLabel={confirm.change.role ? "Change role" : confirm.change.is_active ? "Enable account" : "Disable account"}
          onCancel={() => setConfirm(null)} onConfirm={() => apply(confirm.user, confirm.change)}>
          {confirm.change.role ? <p>{ROLES.find(([v]) => v === confirm.change.role)?.[2]}</p>
            : confirm.change.is_active ? <p>{confirm.user.name} will be able to sign in again with their existing password.</p>
              : <p>{confirm.user.name} is signed out on every device immediately and cannot sign in until an administrator enables the account. Their records are kept.</p>}
          <p className="text-muted">The change is recorded in the audit log.</p>
        </ConfirmDialog>
      )}
    </>
  );
}
