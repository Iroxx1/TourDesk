// Notification center + month calendar with matching concert days (like the Windows 11 clock flyout).
import { useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { BellOff, CalendarDays, CheckCheck, ChevronLeft, ChevronRight, Trash2 } from "lucide-react";
import { api, errorMessage } from "../api/client";
import type { Notification } from "../api/types";
import { qk, useEvents, useNotifications } from "../api/hooks";
import { useSession } from "../auth/session";
import { Button, IconButton, Spinner, cx } from "../components/ui";
import { fmtMonthYear, fmtRelative, isoDay } from "../lib/format";
import { toast, useUi } from "../state/ui";
import { openApp, openArtist, openEvent } from "../state/windows";

function MonthCalendar() {
  const [cursor, setCursor] = useState(() => {
    const d = new Date();
    return new Date(d.getFullYear(), d.getMonth(), 1);
  });
  const first = cursor;
  const last = new Date(cursor.getFullYear(), cursor.getMonth() + 1, 0);
  const { data, isFetching } = useEvents({ scope: "matching", date_from: isoDay(first), date_to: isoDay(last), limit: 200 });
  const byDay = useMemo(() => {
    const m = new Map<string, number>();
    for (const e of data?.items ?? []) m.set(e.date, (m.get(e.date) ?? 0) + 1);
    return m;
  }, [data]);
  const startOffset = (first.getDay() + 6) % 7; // Monday first
  const cells: (Date | null)[] = [...Array.from({ length: startOffset }, () => null)];
  for (let d = 1; d <= last.getDate(); d++) cells.push(new Date(cursor.getFullYear(), cursor.getMonth(), d));
  while (cells.length % 7) cells.push(null);
  const today = isoDay(new Date());
  const shift = (n: number) => setCursor(new Date(cursor.getFullYear(), cursor.getMonth() + n, 1));
  const close = () => useUi.getState().setFlyout(null);

  return (
    <section className="calendar">
      <header className="calendar-head">
        <strong>{fmtMonthYear(isoDay(first))}</strong>
        {isFetching && <Spinner size={14} />}
        <span className="calendar-nav">
          <IconButton size="sm" label="Vorheriger Monat" icon={<ChevronLeft size={16} />} onClick={() => shift(-1)} />
          <IconButton size="sm" label="Nächster Monat" icon={<ChevronRight size={16} />} onClick={() => shift(1)} />
        </span>
      </header>
      <div className="calendar-grid" role="grid">
        {["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"].map((d) => (
          <span key={d} className="calendar-wd">
            {d}
          </span>
        ))}
        {cells.map((d, i) => {
          if (!d) return <span key={i} className="calendar-cell is-empty" />;
          const key = isoDay(d);
          const count = byDay.get(key) ?? 0;
          return (
            <button
              key={key}
              type="button"
              className={cx("calendar-cell", key === today && "is-today", count > 0 && "has-events")}
              title={count ? `${count} passende${count === 1 ? "r" : ""} Termin${count === 1 ? "" : "e"}` : undefined}
              disabled={!count}
              onClick={() => {
                openApp("agenda", { date_from: key, date_to: key, scope: "matching" });
                close();
              }}
            >
              {d.getDate()}
              {count > 0 && <span className="calendar-dot" aria-hidden />}
            </button>
          );
        })}
      </div>
      <button
        type="button"
        className="calendar-footer"
        onClick={() => {
          openApp("agenda");
          close();
        }}
      >
        <CalendarDays size={14} /> Alle passenden Termine öffnen
      </button>
    </section>
  );
}

export function NotificationCenter() {
  const { data, isLoading } = useNotifications();
  const qc = useQueryClient();
  const { readOnly } = useSession();
  const close = () => useUi.getState().setFlyout(null);
  const refresh = () => qc.invalidateQueries({ queryKey: qk.notifications });
  const markRead = useMutation({ mutationFn: (id: number) => api.post(`/api/notifications/${id}/read`), onSuccess: refresh });
  const markAll = useMutation({ mutationFn: () => api.post("/api/notifications/read-all"), onSuccess: refresh, onError: (e) => toast(errorMessage(e), "error") });
  const clearRead = useMutation({ mutationFn: () => api.del("/api/notifications"), onSuccess: refresh, onError: (e) => toast(errorMessage(e), "error") });

  const openNotification = (n: Notification) => {
    if (!n.read_at && !readOnly) markRead.mutate(n.id);
    if (n.event_id) openEvent(n.event_id, { title: n.title });
    else if (n.artist_id) openArtist(n.artist_id);
    close();
  };

  const items = data?.items ?? [];
  return (
    <div className="flyout notification-center" role="dialog" aria-label="Benachrichtigungen">
      <section className="notif-panel">
        <header className="notif-head">
          <h2>Benachrichtigungen</h2>
          <span className="notif-actions">
            <IconButton size="sm" label="Alle als gelesen markieren" icon={<CheckCheck size={16} />} disabled={readOnly || !data?.unread} onClick={() => markAll.mutate()} />
            <IconButton
              size="sm"
              label="Gelesene löschen"
              icon={<Trash2 size={16} />}
              disabled={readOnly || !items.some((n) => n.read_at)}
              onClick={() => clearRead.mutate()}
            />
          </span>
        </header>
        <div className="notif-list">
          {isLoading && <Spinner label="Lädt" />}
          {!isLoading && !items.length && (
            <div className="notif-empty">
              <BellOff size={28} />
              <p>Keine neuen Benachrichtigungen</p>
              <span>Neue Termine, Ticketstarts und Absagen deiner Künstler erscheinen hier.</span>
            </div>
          )}
          {items.map((n) => (
            <button key={n.id} type="button" className={cx("notif-item", !n.read_at && "is-unread")} onClick={() => openNotification(n)}>
              <span className="notif-type">{n.type_label}</span>
              <strong className="notif-title">{n.title}</strong>
              {n.body && <span className="notif-body">{n.body}</span>}
              <span className="notif-time">{fmtRelative(n.created_at)}</span>
            </button>
          ))}
        </div>
        {items.length > 0 && (
          <footer className="notif-foot">
            <Button size="sm" variant="subtle" onClick={() => { openApp("settings", { section: "notifications" }); close(); }}>
              Benachrichtigungseinstellungen
            </Button>
          </footer>
        )}
      </section>
      <MonthCalendar />
    </div>
  );
}
