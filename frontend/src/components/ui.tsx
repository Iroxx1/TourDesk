// Fluent / Windows 11 inspired base controls.
import {
  useId,
  useState,
  type AnchorHTMLAttributes,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type KeyboardEvent,
  type ReactNode,
  type Ref,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from "react";
import { AlertCircle, CheckCircle2, ChevronLeft, ChevronRight, Info, Loader2, Search, TriangleAlert, X } from "lucide-react";
import type { User } from "../api/types";
import { errorMessage } from "../api/client";
import { initials, hueFor } from "../lib/format";
import { mediaSrc } from "../lib/urls";

export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

// ----------------------------------------------------------------------------- buttons
type ButtonVariant = "default" | "accent" | "subtle" | "danger" | "ghost";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: "sm" | "md" | "lg";
  icon?: ReactNode;
  loading?: boolean;
  ref?: Ref<HTMLButtonElement>;
}

export function Button({ variant = "default", size = "md", icon, loading, children, className, disabled, type, ...rest }: ButtonProps) {
  return (
    <button
      type={type ?? "button"}
      className={cx("btn", `btn-${variant}`, `btn-${size}`, !children && "btn-icon-only", className)}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...rest}
    >
      {loading ? <Loader2 className="spin" size={16} aria-hidden /> : icon}
      {children && <span className="btn-label">{children}</span>}
    </button>
  );
}

interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  label: string;
  icon: ReactNode;
  variant?: ButtonVariant;
  size?: "sm" | "md" | "lg";
  active?: boolean;
  ref?: Ref<HTMLButtonElement>;
}

export function IconButton({ label, icon, variant = "subtle", size = "md", active, className, type, ...rest }: IconButtonProps) {
  return (
    <button
      type={type ?? "button"}
      className={cx("btn", `btn-${variant}`, `btn-${size}`, "btn-icon-only", active && "is-active", className)}
      aria-label={label}
      title={label}
      {...rest}
    >
      {icon}
    </button>
  );
}

interface LinkButtonProps extends AnchorHTMLAttributes<HTMLAnchorElement> {
  variant?: ButtonVariant;
  size?: "sm" | "md" | "lg";
  icon?: ReactNode;
  external?: boolean;
}

export function LinkButton({ variant = "default", size = "md", icon, external = true, children, className, href, ...rest }: LinkButtonProps) {
  if (!href) return null;
  return (
    <a
      className={cx("btn", `btn-${variant}`, `btn-${size}`, !children && "btn-icon-only", className)}
      href={href}
      {...(external ? { target: "_blank", rel: "noopener noreferrer nofollow" } : {})}
      {...rest}
    >
      {icon}
      {children && <span className="btn-label">{children}</span>}
    </a>
  );
}

// ----------------------------------------------------------------------------- inputs
interface ToggleProps {
  checked: boolean;
  onChange(value: boolean): void;
  label?: ReactNode;
  description?: ReactNode;
  disabled?: boolean;
  showState?: boolean;
  className?: string;
}

export function Toggle({ checked, onChange, label, description, disabled, showState = true, className }: ToggleProps) {
  const id = useId();
  return (
    <div className={cx("toggle-row", disabled && "is-disabled", className)}>
      {(label || description) && (
        <label htmlFor={id} className="toggle-text">
          {label && <span className="toggle-label">{label}</span>}
          {description && <span className="toggle-desc">{description}</span>}
        </label>
      )}
      <span className="toggle-control">
        {showState && <span className="toggle-state">{checked ? "Ein" : "Aus"}</span>}
        <button
          id={id}
          type="button"
          role="switch"
          aria-checked={checked}
          className={cx("toggle", checked && "is-on")}
          disabled={disabled}
          onClick={() => onChange(!checked)}
        >
          <span className="toggle-knob" />
        </button>
      </span>
    </div>
  );
}

interface CheckboxProps {
  checked: boolean;
  onChange(value: boolean): void;
  label: ReactNode;
  disabled?: boolean;
}

export function Checkbox({ checked, onChange, label, disabled }: CheckboxProps) {
  return (
    <label className={cx("checkbox", disabled && "is-disabled")}>
      <input type="checkbox" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
      <span className="checkbox-box" aria-hidden />
      <span>{label}</span>
    </label>
  );
}

interface FieldProps {
  label?: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  children: ReactNode;
  htmlFor?: string;
  className?: string;
}

export function Field({ label, hint, error, children, htmlFor, className }: FieldProps) {
  return (
    <div className={cx("field", error ? "has-error" : null, className)}>
      {label && (
        <label className="field-label" htmlFor={htmlFor}>
          {label}
        </label>
      )}
      {children}
      {error ? <div className="field-error">{error}</div> : hint ? <div className="field-hint">{hint}</div> : null}
    </div>
  );
}

interface TextFieldProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  icon?: ReactNode;
  ref?: Ref<HTMLInputElement>;
}

export function TextField({ label, hint, error, icon, className, id, ...rest }: TextFieldProps) {
  const autoId = useId();
  const inputId = id ?? autoId;
  return (
    <Field label={label} hint={hint} error={error} htmlFor={inputId} className={className}>
      <div className={cx("input-wrap", icon ? "has-icon" : null)}>
        {icon && <span className="input-icon">{icon}</span>}
        <input id={inputId} className="input" aria-invalid={error ? true : undefined} {...rest} />
      </div>
    </Field>
  );
}

interface TextAreaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  label?: ReactNode;
  hint?: ReactNode;
}

export function TextArea({ label, hint, className, id, ...rest }: TextAreaProps) {
  const autoId = useId();
  return (
    <Field label={label} hint={hint} htmlFor={id ?? autoId} className={className}>
      <textarea id={id ?? autoId} className="input textarea" {...rest} />
    </Field>
  );
}

interface SelectProps extends Omit<SelectHTMLAttributes<HTMLSelectElement>, "onChange"> {
  label?: ReactNode;
  hint?: ReactNode;
  options: { value: string; label: string }[];
  onChange(value: string): void;
}

export function Select({ label, hint, options, onChange, className, id, ...rest }: SelectProps) {
  const autoId = useId();
  return (
    <Field label={label} hint={hint} htmlFor={id ?? autoId} className={className}>
      <div className="select-wrap">
        <select id={id ?? autoId} className="input select" onChange={(e) => onChange(e.target.value)} {...rest}>
          {options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </div>
    </Field>
  );
}

interface SearchBoxProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "onChange"> {
  value: string;
  onChange(value: string): void;
  ref?: Ref<HTMLInputElement>;
}

export function SearchBox({ value, onChange, className, placeholder = "Suchen", ...rest }: SearchBoxProps) {
  return (
    <div className={cx("searchbox", className)}>
      <Search size={16} className="searchbox-icon" aria-hidden />
      <input
        type="search"
        className="input"
        value={value}
        placeholder={placeholder}
        aria-label={placeholder}
        onChange={(e) => onChange(e.target.value)}
        {...rest}
      />
      {value && (
        <button type="button" className="searchbox-clear" aria-label="Suche leeren" onClick={() => onChange("")}>
          <X size={14} />
        </button>
      )}
    </div>
  );
}

interface SegmentedProps<T extends string> {
  value: T;
  onChange(value: T): void;
  options: { value: T; label: ReactNode; icon?: ReactNode }[];
  label?: string;
  disabled?: boolean;
  className?: string;
}

export function Segmented<T extends string>({ value, onChange, options, label, disabled, className }: SegmentedProps<T>) {
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const idx = options.findIndex((o) => o.value === value);
    if (e.key === "ArrowRight" || e.key === "ArrowDown") {
      e.preventDefault();
      onChange(options[(idx + 1) % options.length].value);
    } else if (e.key === "ArrowLeft" || e.key === "ArrowUp") {
      e.preventDefault();
      onChange(options[(idx - 1 + options.length) % options.length].value);
    }
  };
  return (
    <div className={cx("segmented", className)} role="radiogroup" aria-label={label} onKeyDown={onKey}>
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={o.value === value}
          tabIndex={o.value === value ? 0 : -1}
          className={cx("segmented-item", o.value === value && "is-selected")}
          disabled={disabled}
          onClick={() => onChange(o.value)}
        >
          {o.icon}
          <span>{o.label}</span>
        </button>
      ))}
    </div>
  );
}

export interface TabDef<T extends string> {
  id: T;
  label: ReactNode;
  icon?: ReactNode;
  count?: number | null;
}

interface TabsProps<T extends string> {
  value: T;
  onChange(value: T): void;
  tabs: TabDef<T>[];
  className?: string;
}

export function Tabs<T extends string>({ value, onChange, tabs, className }: TabsProps<T>) {
  return (
    <div className={cx("tabs", className)} role="tablist">
      {tabs.map((t) => (
        <button
          key={t.id}
          type="button"
          role="tab"
          aria-selected={t.id === value}
          className={cx("tab", t.id === value && "is-selected")}
          onClick={() => onChange(t.id)}
        >
          {t.icon}
          <span>{t.label}</span>
          {t.count !== undefined && t.count !== null && <span className="tab-count">{t.count}</span>}
        </button>
      ))}
    </div>
  );
}

// ----------------------------------------------------------------------------- feedback
export type Tone = "neutral" | "accent" | "success" | "warning" | "danger" | "festival" | "info";

export function Badge({ tone = "neutral", children, className, title }: { tone?: Tone; children: ReactNode; className?: string; title?: string }) {
  return (
    <span className={cx("badge", `badge-${tone}`, className)} title={title}>
      {children}
    </span>
  );
}

export function Spinner({ size = 20, label }: { size?: number; label?: string }) {
  return (
    <span className="spinner" role="status" aria-label={label ?? "Lädt"}>
      <Loader2 size={size} className="spin" aria-hidden />
      {label && <span className="spinner-label">{label}</span>}
    </span>
  );
}

export function Loading({ label = "Wird geladen …" }: { label?: string }) {
  return (
    <div className="loading-block">
      <Spinner label={label} />
    </div>
  );
}

interface EmptyStateProps {
  icon?: ReactNode;
  title: ReactNode;
  text?: ReactNode;
  action?: ReactNode;
  compact?: boolean;
}

export function EmptyState({ icon, title, text, action, compact }: EmptyStateProps) {
  return (
    <div className={cx("empty", compact && "empty-compact")}>
      {icon && <div className="empty-icon">{icon}</div>}
      <div className="empty-title">{title}</div>
      {text && <div className="empty-text">{text}</div>}
      {action && <div className="empty-action">{action}</div>}
    </div>
  );
}

interface InfoBarProps {
  tone?: "info" | "success" | "warning" | "error";
  title?: ReactNode;
  children?: ReactNode;
  action?: ReactNode;
  onClose?: () => void;
  className?: string;
}

export function InfoBar({ tone = "info", title, children, action, onClose, className }: InfoBarProps) {
  const Icon = tone === "success" ? CheckCircle2 : tone === "warning" ? TriangleAlert : tone === "error" ? AlertCircle : Info;
  return (
    <div className={cx("infobar", `infobar-${tone}`, className)} role={tone === "error" ? "alert" : "status"}>
      <Icon size={18} className="infobar-icon" aria-hidden />
      <div className="infobar-body">
        {title && <strong className="infobar-title">{title}</strong>}
        {children && <span className="infobar-text">{children}</span>}
      </div>
      {action && <div className="infobar-action">{action}</div>}
      {onClose && (
        <button type="button" className="infobar-close" aria-label="Schließen" onClick={onClose}>
          <X size={16} />
        </button>
      )}
    </div>
  );
}

export function ErrorView({ error, retry }: { error: unknown; retry?: () => void }) {
  return (
    <div className="error-view">
      <InfoBar tone="error" title="Fehler" action={retry ? <Button size="sm" onClick={retry}>Erneut versuchen</Button> : undefined}>
        {errorMessage(error)}
      </InfoBar>
    </div>
  );
}

export function Skeleton({ lines = 3 }: { lines?: number }) {
  return (
    <div className="skeleton" aria-hidden>
      {Array.from({ length: lines }, (_, i) => (
        <div key={i} className="skeleton-line" />
      ))}
    </div>
  );
}

// ----------------------------------------------------------------------------- layout
interface CardProps {
  title?: ReactNode;
  subtitle?: ReactNode;
  icon?: ReactNode;
  actions?: ReactNode;
  children?: ReactNode;
  className?: string;
  padded?: boolean;
}

export function Card({ title, subtitle, icon, actions, children, className, padded = true }: CardProps) {
  return (
    <section className={cx("card", padded && "card-padded", className)}>
      {(title || actions) && (
        <header className="card-head">
          {icon && <span className="card-icon">{icon}</span>}
          <div className="card-titles">
            {title && <h3 className="card-title">{title}</h3>}
            {subtitle && <div className="card-subtitle">{subtitle}</div>}
          </div>
          {actions && <div className="card-actions">{actions}</div>}
        </header>
      )}
      {children}
    </section>
  );
}

interface SettingRowProps {
  icon?: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  children?: ReactNode;
  onClick?: () => void;
  className?: string;
}

/** A row in the style of the Windows 11 settings app. */
export function SettingRow({ icon, title, description, children, onClick, className }: SettingRowProps) {
  const content = (
    <>
      {icon && <span className="setting-icon">{icon}</span>}
      <span className="setting-text">
        <span className="setting-title">{title}</span>
        {description && <span className="setting-desc">{description}</span>}
      </span>
      {children && <span className="setting-control">{children}</span>}
      {onClick && !children && <ChevronRight size={16} className="setting-chevron" aria-hidden />}
    </>
  );
  if (onClick) {
    return (
      <button type="button" className={cx("setting-row", "is-clickable", className)} onClick={onClick}>
        {content}
      </button>
    );
  }
  return <div className={cx("setting-row", className)}>{content}</div>;
}

export function KeyValue({ items, className }: { items: [ReactNode, ReactNode][]; className?: string }) {
  return (
    <dl className={cx("kv", className)}>
      {items.map(([k, v], i) => (
        <div className="kv-row" key={i}>
          <dt>{k}</dt>
          <dd>{v ?? "–"}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Avatar({ user, size = 32, className }: { user: Pick<User, "username" | "display_name" | "avatar_url">; size?: number; className?: string }) {
  const name = user.display_name || user.username;
  const src = mediaSrc(user.avatar_url);
  const [failed, setFailed] = useState(false);
  const hue = hueFor(name);
  const dims = { width: size, height: size };
  if (src && !failed) {
    return <img className={cx("avatar", className)} src={src} alt="" style={dims} onError={() => setFailed(true)} />;
  }
  return (
    <span
      className={cx("avatar", "avatar-fallback", className)}
      style={{ ...dims, fontSize: Math.round(size * 0.4), background: `linear-gradient(135deg, hsl(${hue} 70% 45%), hsl(${(hue + 40) % 360} 70% 35%))` }}
      aria-hidden
    >
      {initials(name)}
    </span>
  );
}

interface ChipInputProps {
  values: string[];
  onChange(values: string[]): void;
  placeholder?: string;
  label?: ReactNode;
  hint?: ReactNode;
  disabled?: boolean;
  max?: number;
}

export function ChipInput({ values, onChange, placeholder, label, hint, disabled, max = 30 }: ChipInputProps) {
  const [draft, setDraft] = useState("");
  const id = useId();
  const add = () => {
    const v = draft.trim();
    if (!v) return;
    if (!values.some((x) => x.toLowerCase() === v.toLowerCase()) && values.length < max) onChange([...values, v]);
    setDraft("");
  };
  return (
    <Field label={label} hint={hint} htmlFor={id}>
      <div className={cx("chip-input", disabled && "is-disabled")}>
        {values.map((v) => (
          <span key={v} className="chip">
            {v}
            {!disabled && (
              <button type="button" aria-label={`${v} entfernen`} onClick={() => onChange(values.filter((x) => x !== v))}>
                <X size={12} />
              </button>
            )}
          </span>
        ))}
        <input
          id={id}
          className="chip-input-field"
          value={draft}
          disabled={disabled}
          placeholder={values.length ? "" : placeholder}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={add}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === ",") {
              e.preventDefault();
              add();
            } else if (e.key === "Backspace" && !draft && values.length) {
              onChange(values.slice(0, -1));
            }
          }}
        />
      </div>
    </Field>
  );
}

interface PaginationProps {
  offset: number;
  limit: number;
  total: number;
  onChange(offset: number): void;
}

export function Pagination({ offset, limit, total, onChange }: PaginationProps) {
  if (total <= limit) return null;
  const page = Math.floor(offset / limit) + 1;
  const pages = Math.ceil(total / limit);
  return (
    <div className="pagination">
      <IconButton label="Vorherige Seite" icon={<ChevronLeft size={16} />} disabled={offset <= 0} onClick={() => onChange(Math.max(0, offset - limit))} />
      <span className="pagination-label">
        Seite {page} von {pages} · {total.toLocaleString("de-DE")} Einträge
      </span>
      <IconButton label="Nächste Seite" icon={<ChevronRight size={16} />} disabled={offset + limit >= total} onClick={() => onChange(offset + limit)} />
    </div>
  );
}

export function Stat({ label, value, tone, icon, onClick }: { label: ReactNode; value: ReactNode; tone?: Tone; icon?: ReactNode; onClick?: () => void }) {
  const Tag = onClick ? "button" : "div";
  return (
    <Tag type={onClick ? "button" : undefined} className={cx("stat", tone && `stat-${tone}`, onClick && "is-clickable")} onClick={onClick}>
      {icon && <span className="stat-icon">{icon}</span>}
      <span className="stat-value">{value}</span>
      <span className="stat-label">{label}</span>
    </Tag>
  );
}
