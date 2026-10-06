// Status badges for tours, events, tickets, crawler and sources.
import { Ban, CalendarClock, CheckCheck, Clock3, PartyPopper, ShieldCheck, Sparkles, Ticket, Users } from "lucide-react";
import type { TourEvent, TourStatus } from "../api/types";
import {
  CRAWL_STATUS_LABELS,
  EVENT_STATUS_LABELS,
  EVENT_TYPE_LABELS,
  JOB_STATUS_LABELS,
  RUN_STATUS_LABELS,
  SOURCE_STATUS_LABELS,
  TICKET_STATUS_LABELS,
} from "../lib/format";
import { Badge, cx, type Tone } from "./ui";

const TOUR_TEXT: Record<TourStatus["state"], string> = {
  on_tour: "AKTUELL AUF TOUR",
  announced: "TOUR ANGEKÜNDIGT",
  not_on_tour: "DERZEIT NICHT AUF TOUR",
};

export function TourStatusPill({ status, size = "md" }: { status: TourStatus; size?: "sm" | "md" }) {
  return (
    <span className={cx("tour-pill", `tour-${status.state}`, size === "sm" && "tour-pill-sm")} title={status.detail}>
      <span className="tour-dot" aria-hidden />
      <span>{TOUR_TEXT[status.state]}</span>
    </span>
  );
}

export function EventTypeBadge({ type }: { type: TourEvent["event_type"] }) {
  if (type === "concert") return null;
  const tone: Tone = type === "festival" ? "festival" : type === "support" ? "info" : "accent";
  const Icon = type === "festival" ? PartyPopper : type === "support" ? Users : Sparkles;
  return (
    <Badge tone={tone}>
      <Icon size={12} aria-hidden />
      {EVENT_TYPE_LABELS[type]}
    </Badge>
  );
}

export function EventStatusBadge({ status }: { status: TourEvent["status"] }) {
  if (status === "scheduled") return null;
  const tone: Tone = status === "cancelled" ? "danger" : "warning";
  const Icon = status === "cancelled" ? Ban : CalendarClock;
  return (
    <Badge tone={tone}>
      <Icon size={12} aria-hidden />
      {EVENT_STATUS_LABELS[status]}
    </Badge>
  );
}

export function ticketTone(status: string): Tone {
  switch (status) {
    case "available":
    case "free":
      return "success";
    case "limited":
    case "presale":
      return "warning";
    case "sold_out":
    case "cancelled":
      return "danger";
    case "box_office":
    case "not_on_sale":
      return "info";
    default:
      return "neutral";
  }
}

export function TicketBadge({ status }: { status: string }) {
  if (!status || status === "unknown") return null;
  return (
    <Badge tone={ticketTone(status)}>
      <Ticket size={12} aria-hidden />
      {TICKET_STATUS_LABELS[status] ?? status}
    </Badge>
  );
}

export function ConfirmationBadge({ event }: { event: Pick<TourEvent, "source_count" | "is_confirmed" | "best_trust"> }) {
  if (!event.is_confirmed) {
    return (
      <Badge tone="warning" title="Noch nicht durch eine vertrauenswürdige Quelle bestätigt">
        <Clock3 size={12} aria-hidden />
        Unbestätigt
      </Badge>
    );
  }
  if (event.source_count >= 2) {
    return (
      <Badge tone="success" title={`${event.source_count} Quellen bestätigen diesen Termin`}>
        <CheckCheck size={12} aria-hidden />
        {event.source_count} Quellen
      </Badge>
    );
  }
  if (event.best_trust <= 2) {
    return (
      <Badge tone="success" title="Von offizieller Quelle bestätigt">
        <ShieldCheck size={12} aria-hidden />
        Offiziell
      </Badge>
    );
  }
  return null;
}

export function CrawlStatusBadge({ status }: { status: string }) {
  const tone: Tone = status === "ok" ? "success" : status === "partial" ? "warning" : status === "error" ? "danger" : "neutral";
  return <Badge tone={tone}>{CRAWL_STATUS_LABELS[status] ?? status}</Badge>;
}

export function SourceStatusBadge({ status }: { status: string }) {
  const tone: Tone = status === "ok" ? "success" : status === "warning" ? "warning" : status === "error" ? "danger" : "neutral";
  return <Badge tone={tone}>{SOURCE_STATUS_LABELS[status] ?? status}</Badge>;
}

export function JobStatusBadge({ status }: { status: string }) {
  const tone: Tone =
    status === "succeeded" ? "success" : status === "running" ? "accent" : status === "partial" ? "warning" : status === "failed" ? "danger" : "neutral";
  return <Badge tone={tone}>{JOB_STATUS_LABELS[status] ?? status}</Badge>;
}

export function RunStatusBadge({ status }: { status: string }) {
  const tone: Tone = status === "success" ? "success" : status === "running" ? "accent" : status === "partial" ? "warning" : "danger";
  const emoji = status === "success" ? "🟢" : status === "partial" ? "🟡" : status === "failed" ? "🔴" : "🔵";
  return (
    <Badge tone={tone}>
      <span aria-hidden>{emoji}</span> {RUN_STATUS_LABELS[status] ?? status}
    </Badge>
  );
}

export function StatusDot({ tone }: { tone: "ok" | "warn" | "error" | "off" }) {
  return <span className={cx("status-dot", `status-dot-${tone}`)} aria-hidden />;
}
