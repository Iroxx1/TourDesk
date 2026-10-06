// Lock-screen style login, first-run setup and forced password change.
import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Eye, EyeOff, LogOut, ShieldCheck } from "lucide-react";
import { api, errorMessage, setCsrfToken } from "../api/client";
import type { Me } from "../api/types";
import { qk } from "../api/hooks";
import { Logo } from "../components/Logo";
import { Button, Checkbox, InfoBar, TextField } from "../components/ui";
import { fmtClock, fmtLongDate, isoDay } from "../lib/format";
import { cachedDesign } from "../lib/theme";
import { wallpaperUrl } from "../lib/urls";

function LockClock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const t = window.setInterval(() => setNow(new Date()), 10_000);
    return () => window.clearInterval(t);
  }, []);
  return (
    <div className="lock-clock" aria-hidden>
      <div className="lock-time">{fmtClock(now)}</div>
      <div className="lock-date">{fmtLongDate(isoDay(now))}</div>
    </div>
  );
}

export function AuthLayout({ children, version }: { children: ReactNode; version?: string }) {
  const wallpaper = cachedDesign().wallpaper || "bloom";
  return (
    <div className="auth-screen">
      <div className="wallpaper">
        <div className="wallpaper-image" style={{ backgroundImage: `url("${wallpaperUrl(wallpaper)}")` }} />
        <div className="wallpaper-tint auth-tint" />
      </div>
      <LockClock />
      <main className="auth-card">{children}</main>
      <footer className="auth-footer">TourDesk{version ? ` ${version}` : ""} · Persönliche Konzert- und Tourüberwachung</footer>
    </div>
  );
}

function PasswordField({ label, value, onChange, autoComplete, autoFocus, hint, error }: { label: string; value: string; onChange(v: string): void; autoComplete: string; autoFocus?: boolean; hint?: string; error?: string }) {
  const [show, setShow] = useState(false);
  return (
    <div className="password-field">
      <TextField label={label} type={show ? "text" : "password"} value={value} onChange={(e) => onChange(e.target.value)} autoComplete={autoComplete} autoFocus={autoFocus} required hint={hint} error={error} />
      <button type="button" className="password-eye" aria-label={show ? "Passwort verbergen" : "Passwort anzeigen"} onClick={() => setShow(!show)}>
        {show ? <EyeOff size={16} /> : <Eye size={16} />}
      </button>
    </div>
  );
}

function useAcceptMe() {
  const qc = useQueryClient();
  return (me: Me) => {
    setCsrfToken(me.csrf_token);
    qc.removeQueries({ predicate: (q) => q.queryKey[0] !== "me" && q.queryKey[0] !== "setup-status" });
    qc.setQueryData(qk.me, me);
    qc.invalidateQueries({ queryKey: ["setup-status"] });
  };
}

export function LoginScreen({ version, expired }: { version?: string; expired?: boolean }) {
  const accept = useAcceptMe();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(true);
  const login = useMutation({
    mutationFn: () => api.post<Me>("/api/auth/login", { username: username.trim(), password, remember }),
    onSuccess: accept,
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (username.trim() && password) login.mutate();
  };
  return (
    <AuthLayout version={version}>
      <div className="auth-logo">
        <Logo size={72} />
      </div>
      <h1 className="auth-title">TourDesk</h1>
      <p className="auth-sub">Melde dich an, um deine Konzerte zu sehen.</p>
      {expired && !login.error && (
        <InfoBar tone="warning" title="Sitzung abgelaufen.">
          Bitte erneut anmelden.
        </InfoBar>
      )}
      {login.error && <InfoBar tone="error">{errorMessage(login.error)}</InfoBar>}
      <form className="auth-form" onSubmit={submit}>
        <TextField label="Benutzername oder E-Mail" value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" autoFocus required />
        <PasswordField label="Passwort" value={password} onChange={setPassword} autoComplete="current-password" />
        <Checkbox checked={remember} onChange={setRemember} label="Angemeldet bleiben" />
        <Button type="submit" variant="accent" size="lg" loading={login.isPending} icon={<ArrowRight size={18} />} className="auth-submit">
          Anmelden
        </Button>
      </form>
      <p className="auth-hint">Passwort vergessen? Ein Administrator kann es in der Benutzerverwaltung zurücksetzen.</p>
    </AuthLayout>
  );
}

export function SetupScreen({ allowed, version }: { allowed: boolean; version?: string }) {
  const accept = useAcceptMe();
  const [username, setUsername] = useState("admin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const mismatch = confirm.length > 0 && confirm !== password;
  const setup = useMutation({
    mutationFn: () => api.post<Me>("/api/auth/setup", { username: username.trim(), email: email.trim(), password }),
    onSuccess: accept,
  });
  return (
    <AuthLayout version={version}>
      <div className="auth-logo">
        <Logo size={64} />
      </div>
      <h1 className="auth-title">Willkommen bei TourDesk</h1>
      <p className="auth-sub">Erstelle das Administrator-Konto. Weitere Benutzer legst du danach in der Administration an.</p>
      {!allowed && (
        <InfoBar tone="warning" title="Ersteinrichtung nur im lokalen Netzwerk.">
          Öffne TourDesk über die lokale IP-Adresse des Servers (z. B. http://192.168.x.x:8080) oder setze TOURDESK_ALLOW_REMOTE_SETUP=true.
        </InfoBar>
      )}
      {setup.error && <InfoBar tone="error">{errorMessage(setup.error)}</InfoBar>}
      <form
        className="auth-form"
        onSubmit={(e) => {
          e.preventDefault();
          if (!mismatch) setup.mutate();
        }}
      >
        <TextField label="Benutzername" value={username} onChange={(e) => setUsername(e.target.value)} minLength={3} maxLength={32} autoComplete="username" required />
        <TextField label="E-Mail-Adresse" type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" required autoFocus />
        <PasswordField label="Passwort" value={password} onChange={setPassword} autoComplete="new-password" hint="Mindestens 10 Zeichen, nicht zu einfach." />
        <PasswordField label="Passwort wiederholen" value={confirm} onChange={setConfirm} autoComplete="new-password" error={mismatch ? "Die Passwörter stimmen nicht überein." : undefined} />
        <Button type="submit" variant="accent" size="lg" loading={setup.isPending} disabled={!allowed || mismatch || password.length < 10} icon={<ShieldCheck size={18} />} className="auth-submit">
          Admin-Konto erstellen
        </Button>
      </form>
    </AuthLayout>
  );
}

export function PasswordChangeScreen({ me, onLogout }: { me: Me; onLogout(): void }) {
  const qc = useQueryClient();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const mismatch = confirm.length > 0 && confirm !== next;
  const change = useMutation({
    mutationFn: () => api.post("/api/users/me/password", { current_password: current, new_password: next }),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.me }),
  });
  return (
    <AuthLayout version={me.version}>
      <div className="auth-logo">
        <Logo size={56} />
      </div>
      <h1 className="auth-title">Neues Passwort festlegen</h1>
      <p className="auth-sub">
        Hallo {me.user.display_name || me.user.username}, bitte ändere dein temporäres Passwort, bevor du TourDesk verwendest.
      </p>
      {change.error && <InfoBar tone="error">{errorMessage(change.error)}</InfoBar>}
      <form
        className="auth-form"
        onSubmit={(e) => {
          e.preventDefault();
          if (!mismatch) change.mutate();
        }}
      >
        <PasswordField label="Aktuelles (temporäres) Passwort" value={current} onChange={setCurrent} autoComplete="current-password" autoFocus />
        <PasswordField label="Neues Passwort" value={next} onChange={setNext} autoComplete="new-password" hint="Mindestens 10 Zeichen." />
        <PasswordField label="Neues Passwort wiederholen" value={confirm} onChange={setConfirm} autoComplete="new-password" error={mismatch ? "Die Passwörter stimmen nicht überein." : undefined} />
        <Button type="submit" variant="accent" size="lg" loading={change.isPending} disabled={mismatch || next.length < 10 || !current} className="auth-submit">
          Passwort speichern
        </Button>
      </form>
      <Button variant="subtle" icon={<LogOut size={16} />} onClick={onLogout}>
        Abmelden
      </Button>
    </AuthLayout>
  );
}
