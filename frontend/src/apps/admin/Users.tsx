// Admin user management: list, create, edit, roles, deactivate, delete, reset password, view as user.
import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Eye, KeyRound, Lock, Mic2, PartyPopper, Plus, ScrollText, ShieldCheck, SlidersHorizontal, Trash2, Unlock, UserRound } from "lucide-react";
import { api, errorMessage } from "../../api/client";
import type { AdminUser, Me } from "../../api/types";
import { qk, useAdminUsers } from "../../api/hooks";
import { useSession } from "../../auth/session";
import { ArtistImage } from "../../components/ArtistImage";
import { CrawlStatusBadge } from "../../components/badges";
import { Dialog } from "../../components/Dialog";
import { Avatar, Badge, Button, Card, Checkbox, EmptyState, ErrorView, KeyValue, Loading, SearchBox, Segmented, Select, Tabs, TextField, Toggle, cx } from "../../components/ui";
import { LEVEL_LABELS, fmtDateTime, fmtRelative } from "../../lib/format";
import { confirmDialog, toast } from "../../state/ui";
import { useWindows } from "../../state/windows";
import type { AdminNav } from "./AdminApp";
import { useAdminAction, useAdminUser, useAdminUserArtists, useAdminUserAudit, useAdminUserFilters } from "./hooks";

function CreateUserDialog({ open, onClose, onCreated }: { open: boolean; onClose(): void; onCreated(id: number): void }) {
  const [form, setForm] = useState({ username: "", email: "", display_name: "", role: "user", password: "", generate: true, must_change: true });
  const [temporary, setTemporary] = useState<string | null>(null);
  const qc = useQueryClient();
  const create = useMutation({
    mutationFn: () =>
      api.post<{ user: AdminUser; temporary_password: string | null }>("/api/admin/users", {
        username: form.username.trim(),
        email: form.email.trim(),
        display_name: form.display_name.trim() || null,
        role: form.role,
        password: form.generate ? null : form.password,
        must_change_password: form.must_change,
      }),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["admin"] });
      toast(`Benutzer ${r.user.username} angelegt`, "success");
      onCreated(r.user.id);
      if (r.temporary_password) setTemporary(r.temporary_password);
      else close();
    },
    onError: (e) => toast(errorMessage(e), "error"),
  });
  const close = () => {
    setTemporary(null);
    setForm({ username: "", email: "", display_name: "", role: "user", password: "", generate: true, must_change: true });
    onClose();
  };
  return (
    <Dialog
      open={open}
      title={temporary ? "Benutzer angelegt" : "Neuer Benutzer"}
      onClose={close}
      footer={
        temporary ? (
          <Button variant="accent" onClick={close}>
            Fertig
          </Button>
        ) : (
          <>
            <Button variant="accent" loading={create.isPending} disabled={!form.username.trim() || !form.email.trim() || (!form.generate && form.password.length < 10)} onClick={() => create.mutate()}>
              Anlegen
            </Button>
            <Button onClick={close}>Abbrechen</Button>
          </>
        )
      }
    >
      {temporary ? (
        <TemporaryPassword password={temporary} />
      ) : (
        <form
          className="form-grid"
          onSubmit={(e) => {
            e.preventDefault();
            create.mutate();
          }}
        >
          <TextField label="Benutzername" required minLength={3} maxLength={32} value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} autoFocus />
          <TextField label="E-Mail" type="email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
          <TextField label="Anzeigename (optional)" value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })} />
          <Select
            label="Rolle"
            value={form.role}
            onChange={(role) => setForm({ ...form, role })}
            options={[
              { value: "user", label: "Benutzer" },
              { value: "admin", label: "Administrator" },
            ]}
          />
          <div className="span-2">
            <Checkbox checked={form.generate} onChange={(generate) => setForm({ ...form, generate })} label="Temporäres Passwort automatisch erzeugen" />
          </div>
          {!form.generate && (
            <TextField label="Passwort" type="password" minLength={10} value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} autoComplete="new-password" className="span-2" hint="Mindestens 10 Zeichen." />
          )}
          <div className="span-2">
            <Checkbox checked={form.must_change || form.generate} disabled={form.generate} onChange={(must_change) => setForm({ ...form, must_change })} label="Passwort beim ersten Login ändern" />
          </div>
        </form>
      )}
    </Dialog>
  );
}

function TemporaryPassword({ password }: { password: string }) {
  return (
    <div className="temp-password">
      <p>Das temporäre Passwort wird nur jetzt angezeigt. Bitte sicher an den Benutzer weitergeben – beim ersten Login muss es geändert werden.</p>
      <code className="temp-password-value">{password}</code>
      <Button
        size="sm"
        onClick={() =>
          navigator.clipboard
            ?.writeText(password)
            .then(() => toast("In die Zwischenablage kopiert", "success"))
            .catch(() => toast("Kopieren nicht möglich", "error"))
        }
      >
        Kopieren
      </Button>
    </div>
  );
}

function ResetPasswordDialog({ user, open, onClose }: { user: AdminUser; open: boolean; onClose(): void }) {
  const [manual, setManual] = useState("");
  const [useManual, setUseManual] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const reset = useAdminAction(
    () => api.post<{ temporary_password: string | null }>(`/api/admin/users/${user.id}/password`, { new_password: useManual ? manual : null, must_change_password: true }),
    "Passwort zurückgesetzt – alle Sitzungen des Benutzers wurden beendet.",
  );
  const close = () => {
    setResult(null);
    setManual("");
    onClose();
  };
  return (
    <Dialog
      open={open}
      size="sm"
      title={`Passwort von ${user.username} zurücksetzen`}
      onClose={close}
      footer={
        result ? (
          <Button variant="accent" onClick={close}>
            Fertig
          </Button>
        ) : (
          <>
            <Button
              variant="danger"
              loading={reset.isPending}
              disabled={useManual && manual.length < 10}
              onClick={() =>
                reset.mutate(undefined, {
                  onSuccess: (r) => (r.temporary_password ? setResult(r.temporary_password) : close()),
                })
              }
            >
              Zurücksetzen
            </Button>
            <Button onClick={close}>Abbrechen</Button>
          </>
        )
      }
    >
      {result ? (
        <TemporaryPassword password={result} />
      ) : (
        <div className="stack-sm">
          <Checkbox checked={useManual} onChange={setUseManual} label="Passwort selbst festlegen" />
          {useManual ? (
            <TextField label="Neues Passwort" type="password" minLength={10} value={manual} onChange={(e) => setManual(e.target.value)} autoComplete="new-password" />
          ) : (
            <p className="muted">Es wird ein sicheres temporäres Passwort erzeugt.</p>
          )}
          <p className="muted small">Der Benutzer muss das Passwort beim nächsten Login ändern. Bestehende Sitzungen werden abgemeldet.</p>
        </div>
      )}
    </Dialog>
  );
}

type DetailTab = "profile" | "artists" | "filters" | "audit";

function UserDetail({ userId, onDeleted }: { userId: number; onDeleted(): void }) {
  const { me } = useSession();
  const qc = useQueryClient();
  const { data: user, isLoading, error, refetch } = useAdminUser(userId);
  const [tab, setTab] = useState<DetailTab>("profile");
  const [form, setForm] = useState({ username: "", email: "", display_name: "", role: "user" as "user" | "admin", is_active: true, must_change_password: false });
  const [resetOpen, setResetOpen] = useState(false);
  const artists = useAdminUserArtists(tab === "artists" ? userId : null);
  const filters = useAdminUserFilters(tab === "filters" ? userId : null);
  const audit = useAdminUserAudit(tab === "audit" ? userId : null);

  useEffect(() => {
    if (user)
      setForm({
        username: user.username,
        email: user.email,
        display_name: user.display_name ?? "",
        role: user.role,
        is_active: user.is_active,
        must_change_password: user.must_change_password,
      });
  }, [user]);

  const save = useAdminAction(() => api.patch<AdminUser>(`/api/admin/users/${userId}`, { ...form, display_name: form.display_name.trim() || null }), "Benutzer gespeichert");
  const unlock = useAdminAction(() => api.post(`/api/admin/users/${userId}/unlock`), "Sperre aufgehoben");
  const remove = useAdminAction(() => api.del(`/api/admin/users/${userId}`), "Benutzer gelöscht");
  const impersonate = useMutation({
    mutationFn: () => api.post<Me>(`/api/admin/users/${userId}/impersonate`),
    onSuccess: (next) => {
      useWindows.getState().closeAll();
      qc.removeQueries({ predicate: (q) => q.queryKey[0] !== "me" });
      qc.setQueryData(qk.me, next);
      toast(`Du siehst jetzt die Ansicht von ${next.user.username}`, "info");
    },
    onError: (e) => toast(errorMessage(e), "error"),
  });

  if (isLoading) return <Loading />;
  if (error || !user) return <ErrorView error={error} retry={refetch} />;
  const self = user.id === me.user.id;
  const locked = user.locked_until && new Date(user.locked_until) > new Date();

  return (
    <div className="user-detail">
      <header className="user-detail-head">
        <Avatar user={user} size={56} />
        <div className="user-detail-title">
          <h3>
            {user.display_name || user.username} {user.role === "admin" && <Badge tone="accent">Admin</Badge>} {!user.is_active && <Badge>deaktiviert</Badge>}{" "}
            {locked && <Badge tone="danger">gesperrt</Badge>}
          </h3>
          <div className="muted">
            {user.username} · {user.email}
          </div>
          <div className="muted small">
            Letzter Login: {user.last_login_at ? fmtDateTime(user.last_login_at) : "noch nie"} · zuletzt aktiv {fmtRelative(user.last_seen_at)} · {user.session_count} Sitzung(en)
          </div>
        </div>
        <div className="user-detail-actions">
          <Button variant="accent" icon={<Eye size={16} />} disabled={self || !user.is_active} loading={impersonate.isPending} onClick={() => impersonate.mutate()} title={self ? "Eigene Ansicht nicht simulierbar" : undefined}>
            Ansicht als Benutzer öffnen
          </Button>
        </div>
      </header>

      <Tabs<DetailTab>
        value={tab}
        onChange={setTab}
        tabs={[
          { id: "profile", label: "Profil", icon: <UserRound size={15} /> },
          { id: "artists", label: "Künstler", icon: <Mic2 size={15} />, count: user.artist_count },
          { id: "filters", label: "Filter", icon: <SlidersHorizontal size={15} />, count: user.location_rule_count },
          { id: "audit", label: "Aktivität", icon: <ScrollText size={15} /> },
        ]}
      />

      {tab === "profile" && (
        <div className="stack">
          <Card>
            <form
              className="form-grid"
              onSubmit={(e) => {
                e.preventDefault();
                save.mutate();
              }}
            >
              <TextField label="Benutzername" value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} minLength={3} maxLength={32} required />
              <TextField label="E-Mail" type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} required />
              <TextField label="Anzeigename" value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })} />
              <Select
                label="Rolle"
                value={form.role}
                disabled={self}
                onChange={(role) => setForm({ ...form, role: role as "user" | "admin" })}
                options={[
                  { value: "user", label: "Benutzer" },
                  { value: "admin", label: "Administrator" },
                ]}
              />
              <Toggle label="Konto aktiv" description="Deaktivierte Benutzer können sich nicht anmelden" checked={form.is_active} disabled={self} onChange={(is_active) => setForm({ ...form, is_active })} />
              <Toggle label="Passwortänderung erzwingen" checked={form.must_change_password} onChange={(must_change_password) => setForm({ ...form, must_change_password })} />
              <div className="form-actions span-2">
                <Button type="submit" variant="accent" loading={save.isPending}>
                  Speichern
                </Button>
              </div>
            </form>
          </Card>
          <Card title="Sicherheit">
            <div className="button-row">
              <Button icon={<KeyRound size={16} />} onClick={() => setResetOpen(true)}>
                Passwort zurücksetzen
              </Button>
              {(locked || user.failed_login_count > 0) && (
                <Button icon={<Unlock size={16} />} loading={unlock.isPending} onClick={() => unlock.mutate()}>
                  Sperre aufheben ({user.failed_login_count} Fehlversuche)
                </Button>
              )}
              <Button
                variant="danger"
                icon={<Trash2 size={16} />}
                disabled={self}
                loading={remove.isPending}
                onClick={async () => {
                  if (
                    await confirmDialog({
                      title: `${user.username} löschen?`,
                      message: "Der Benutzer und alle persönlichen Daten (Künstlerliste, Filter, Einstellungen) werden endgültig gelöscht.",
                      confirmLabel: "Endgültig löschen",
                      danger: true,
                    })
                  )
                    remove.mutate(undefined, { onSuccess: onDeleted });
                }}
              >
                Benutzer löschen
              </Button>
            </div>
            <KeyValue
              items={[
                ["Angelegt", fmtDateTime(user.created_at)],
                ["Fehlgeschlagene Logins", String(user.failed_login_count)],
                ["Gesperrt bis", user.locked_until ? fmtDateTime(user.locked_until) : "–"],
                ["Künstler", `${user.active_artist_count} aktiv / ${user.artist_count}`],
              ]}
            />
          </Card>
          <ResetPasswordDialog user={user} open={resetOpen} onClose={() => setResetOpen(false)} />
        </div>
      )}

      {tab === "artists" && (
        <Card padded={false}>
          {artists.isLoading && <Loading />}
          {artists.data && !artists.data.length && <EmptyState compact title="Keine Künstler" />}
          <div className="artist-rows">
            {artists.data?.map((a) => (
              <div key={a.id} className={cx("artist-row", a.subscription && !a.subscription.is_active && "is-dim")}>
                <span className="artist-row-main">
                  <ArtistImage artist={a} variant="thumb" className="artist-row-img" />
                  <span className="artist-row-text">
                    <strong>{a.name}</strong>
                    <span className="muted">aktualisiert {fmtRelative(a.last_success_at)}</span>
                  </span>
                </span>
                <CrawlStatusBadge status={a.crawl_status} />
                <Badge tone={a.subscription?.show_festivals ? "festival" : "neutral"}>
                  <PartyPopper size={12} /> Festivals {a.subscription?.show_festivals ? "AN" : "AUS"}
                </Badge>
                <Badge tone={a.subscription?.is_active ? "success" : "neutral"}>{a.subscription?.is_active ? "aktiv" : "inaktiv"}</Badge>
              </div>
            ))}
          </div>
        </Card>
      )}

      {tab === "filters" && (
        <div className="stack">
          {filters.isLoading && <Loading />}
          {filters.data && (
            <>
              <Card title="Ortsregeln">
                {filters.data.locations.length === 0 && <EmptyState compact title="Keine Ortsregeln – alle Orte werden angezeigt" />}
                <ul className="compact-list">
                  {filters.data.locations.map((r) => (
                    <li key={r.key}>
                      <Badge tone="accent">{LEVEL_LABELS[r.level]}</Badge>
                      <span className="compact-main">
                        <strong>{r.label}</strong>
                        <span className="muted">
                          {r.country_name} · {r.description}
                        </span>
                      </span>
                    </li>
                  ))}
                </ul>
              </Card>
              <Card title="Einstellungen">
                <KeyValue
                  items={[
                    ["Zeitraum", filters.data.date_mode === "upcoming" ? "Alle kommenden" : filters.data.date_mode === "months" ? `Nächste ${filters.data.months_ahead} Monate` : `${filters.data.date_from} – ${filters.data.date_to}`],
                    ["Konzerte / Support / Special", [filters.data.include_concerts, filters.data.include_support, filters.data.include_special].map((b) => (b ? "✓" : "✗")).join(" / ")],
                    ["Festivals", filters.data.festival_mode === "artist" ? "pro Künstler" : filters.data.festival_mode === "always" ? "immer" : "nie"],
                    ["Festival-Orte", filters.data.festival_scope === "filters" ? "nur in den Orten" : "überall"],
                    ["Abgesagte anzeigen", filters.data.show_cancelled ? "ja" : "nein"],
                    ["Unbestätigte anzeigen", filters.data.show_unconfirmed ? "ja" : "nein"],
                  ]}
                />
              </Card>
            </>
          )}
        </div>
      )}

      {tab === "audit" && (
        <Card padded={false}>
          {audit.isLoading && <Loading />}
          {audit.data && !audit.data.length && <EmptyState compact title="Keine Einträge" />}
          {audit.data && audit.data.length > 0 && (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Zeit</th>
                    <th>Aktion</th>
                    <th>Durch</th>
                    <th>Ziel</th>
                    <th>IP</th>
                  </tr>
                </thead>
                <tbody>
                  {audit.data.map((a) => (
                    <tr key={a.id} className={cx(!a.success && "is-error")}>
                      <td>{fmtDateTime(a.created_at)}</td>
                      <td>
                        <code>{a.action}</code>
                      </td>
                      <td>{a.actor}</td>
                      <td>{a.target}</td>
                      <td className="muted">{a.ip}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      )}
    </div>
  );
}

export function UsersSection({ nav }: { nav: AdminNav }) {
  const [q, setQ] = useState("");
  const [role, setRole] = useState<"all" | "admin" | "user">("all");
  const [selected, setSelected] = useState<number | null>((nav.params.userId as number) ?? null);
  const [creating, setCreating] = useState(false);
  const { data, isLoading } = useAdminUsers(q.trim());
  useEffect(() => {
    if (nav.params.userId) setSelected(Number(nav.params.userId));
  }, [nav.params.userId]);
  const list = (data ?? []).filter((u) => role === "all" || u.role === role);

  return (
    <div className="master-detail">
      <div className="master">
        <div className="master-tools">
          <SearchBox value={q} onChange={setQ} placeholder="Benutzer suchen" />
          <Button variant="accent" icon={<Plus size={16} />} onClick={() => setCreating(true)}>
            Neu
          </Button>
        </div>
        <Segmented<"all" | "admin" | "user">
          value={role}
          onChange={setRole}
          options={[
            { value: "all", label: "Alle" },
            { value: "admin", label: "Admins" },
            { value: "user", label: "Benutzer" },
          ]}
        />
        <div className="master-list">
          {isLoading && <Loading />}
          {list.map((u) => (
            <button key={u.id} type="button" className={cx("master-item", selected === u.id && "is-selected", !u.is_active && "is-dim")} onClick={() => setSelected(u.id)}>
              <Avatar user={u} size={34} />
              <span className="master-item-text">
                <strong>
                  {u.display_name || u.username} {u.role === "admin" && <ShieldCheck size={13} className="inline-icon" />}
                  {u.locked_until && new Date(u.locked_until) > new Date() && <Lock size={13} className="inline-icon danger" />}
                </strong>
                <span className="muted">
                  {u.email} · {u.artist_count} Künstler
                </span>
              </span>
            </button>
          ))}
        </div>
      </div>
      <div className="detail">
        {selected ? (
          <UserDetail key={selected} userId={selected} onDeleted={() => setSelected(null)} />
        ) : (
          <EmptyState icon={<UserRound size={30} />} title="Benutzer auswählen" text="Wähle links einen Benutzer, um Details, Künstler, Filter und Aktivität zu sehen – oder öffne seine Ansicht." />
        )}
      </div>
      <CreateUserDialog open={creating} onClose={() => setCreating(false)} onCreated={setSelected} />
    </div>
  );
}
