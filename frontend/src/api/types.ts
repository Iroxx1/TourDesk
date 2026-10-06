// Types mirroring the TourDesk REST API (backend/tourdesk/schemas).

export interface User {
  id: number;
  username: string;
  email: string;
  display_name: string | null;
  role: "user" | "admin";
  is_active: boolean;
  must_change_password: boolean;
  avatar_url: string | null;
  created_at: string;
  last_login_at: string | null;
}

export interface AdminUser extends User {
  last_seen_at: string | null;
  locked_until: string | null;
  failed_login_count: number;
  artist_count: number;
  active_artist_count: number;
  location_rule_count: number;
  session_count: number;
}

export type Theme = "light" | "dark" | "system";

export interface ViewSettings {
  tile_size: "small" | "medium" | "large";
  sort: "next_event" | "name" | "added";
  show_artists_without_events: boolean;
  tile_event_count: number;
  taskbar_labels: boolean;
  open_windows_maximized: boolean;
}

export interface Settings {
  theme: Theme;
  wallpaper: string;
  accent_color: string | null;
  animations: boolean;
  transparency: boolean;
  timezone: string;
  view: ViewSettings;
  notifications: Record<string, boolean>;
}

export interface Me {
  user: User;
  impersonation: { admin: User; started_at: string | null } | null;
  csrf_token: string;
  settings: Settings;
  is_admin: boolean;
  version: string;
  session_expires_at: string;
}

export interface SetupStatus {
  needs_setup: boolean;
  setup_allowed: boolean;
  version: string;
}

export interface Wallpaper {
  key: string;
  name: string;
  theme: "light" | "dark";
  description: string;
}

export interface SettingsOptions {
  wallpapers: Wallpaper[];
  accent_colors: { key: string; name: string }[];
  notification_types: { key: string; name: string }[];
}

export interface Subscription {
  is_active: boolean;
  show_festivals: boolean;
  notify: boolean;
  pinned: boolean;
  sort_order: number;
  created_at: string;
}

export interface ArtistImages {
  thumb: string | null;
  tile: string | null;
  hero: string | null;
  source: string | null;
  source_url: string | null;
}

export interface Artist {
  id: number;
  name: string;
  slug: string;
  genre: string | null;
  country_code: string | null;
  official_website: string | null;
  aliases: string[];
  search_terms: string[];
  external_ids: Record<string, string>;
  images: ArtistImages;
  is_demo: boolean;
  crawl_status: "pending" | "ok" | "partial" | "error" | "disabled";
  last_crawled_at: string | null;
  last_success_at: string | null;
  next_crawl_at: string | null;
  last_error: string | null;
  subscription: Subscription | null;
  can_edit: boolean;
  subscribers?: number;
  upcoming_events?: number;
}

export interface NamedRef {
  id: number;
  name: string;
}

export type EventType = "concert" | "festival" | "support" | "special";
export type EventStatus = "scheduled" | "cancelled" | "postponed" | "rescheduled";

export interface TourEvent {
  id: number;
  artist_id: number;
  artist_name: string;
  title: string | null;
  date: string;
  end_date: string | null;
  start_time: string | null;
  doors_time: string | null;
  timezone: string | null;
  event_type: EventType;
  status: EventStatus;
  ticket_status: string;
  ticket_url: string | null;
  ticket_provider: string | null;
  onsale_at: string | null;
  venue: NamedRef | null;
  venue_name: string | null;
  city: NamedRef | null;
  city_name: string | null;
  region: NamedRef | null;
  country: { id: number; code: string; name: string } | null;
  tour: NamedRef | null;
  festival: NamedRef | null;
  is_confirmed: boolean;
  confidence: number;
  source_count: number;
  best_trust: number;
  is_listed: boolean;
  primary_source_url: string | null;
  first_seen_at: string;
  last_seen_at: string;
  last_checked_at: string | null;
  updated_at: string;
  matches: boolean | null;
  hidden_reason: string | null;
}

export interface Check {
  ok: boolean | null;
  code: string;
  message: string;
}

export interface Explanation {
  shown: boolean;
  title: string;
  location_match: boolean;
  matched_rule_ids: number[];
  hidden_reason: string | null;
  checks: Check[];
}

export interface EventSourceInfo {
  provider: string;
  provider_label: string;
  source_name: string;
  url: string | null;
  domain: string | null;
  trust_level: number;
  trust_label: string;
  is_active: boolean;
  first_seen_at: string;
  last_seen_at: string;
}

export interface TicketInfo {
  provider: string;
  url: string;
  status: string;
  trust_level: number;
  price_min: number | null;
  price_max: number | null;
  currency: string | null;
  is_active: boolean;
}

export interface EventDetail extends TourEvent {
  sources: EventSourceInfo[];
  tickets: TicketInfo[];
  explanation: Explanation | null;
  artist_image: string | null;
  observations?: Record<string, unknown>[];
}

export interface TourStatus {
  state: "on_tour" | "announced" | "not_on_tour";
  label: string;
  emoji: string;
  detail: string;
  tour_name: string | null;
  start_date: string | null;
  end_date: string | null;
  event_count: number;
  upcoming_count: number;
  next_date: string | null;
  festival_only: boolean;
}

export interface Tile {
  artist: Artist;
  tour_status: TourStatus;
  matching_events: TourEvent[];
  matching_count: number;
  more_count: number;
  total_upcoming: number;
  festival_upcoming: number;
  hidden_festivals: number;
  outside_filters: number;
  last_updated: string | null;
}

export interface Dashboard {
  tiles: Tile[];
  total_matching: number;
  generated_at: string;
  has_location_rules: boolean;
  crawler_last_run: string | null;
}

export interface ArtistEvents {
  artist_id: number;
  tour_status: TourStatus;
  matching: TourEvent[];
  all_events: TourEvent[];
  past_events: TourEvent[];
  tours: NamedRef[];
}

export interface Source {
  id: number;
  scope: "artist" | "venue" | "festival" | "global";
  provider: string;
  provider_label: string;
  name: string;
  url: string | null;
  trust_level: number;
  trust_label: string;
  is_enabled: boolean;
  is_auto: boolean;
  status: "new" | "ok" | "warning" | "error" | "disabled";
  artist_id: number | null;
  artist_name: string | null;
  venue_id: number | null;
  venue_name: string | null;
  festival_id: number | null;
  festival_name: string | null;
  last_attempt_at: string | null;
  last_success_at: string | null;
  last_error_at: string | null;
  last_error: string | null;
  last_error_type: string | null;
  consecutive_failures: number;
  total_failures: number;
  total_runs: number;
  next_attempt_at: string | null;
  last_http_status: number | null;
  last_duration_ms: number | null;
  last_event_count: number | null;
  last_method: string | null;
  config: Record<string, unknown>;
  can_delete: boolean;
}

export interface ArtistSources {
  artist: Artist;
  sources: Source[];
  contributing: Source[];
  addable_providers: string[];
}

export interface LookupItem {
  source: "catalog" | "musicbrainz";
  name: string;
  disambiguation: string | null;
  country: string | null;
  kind: string | null;
  musicbrainz_id: string | null;
  artist_id: number | null;
  followed: boolean;
  genre: string | null;
  score: number | null;
}

export interface Country {
  id: number;
  code: string;
  name: string;
  name_en: string;
  priority: number;
  region_count: number;
}

export interface Region {
  id: number;
  country_id: number;
  country_code: string;
  country_name: string;
  code: string | null;
  name: string;
  local_name: string;
  kind: string;
  parent_id: number | null;
  city_count: number | null;
}

export interface City {
  id: number;
  name: string;
  local_name: string;
  country_id: number;
  country_code: string;
  country_name: string;
  region_id: number | null;
  region_name: string | null;
  population: number;
  latitude: number | null;
  longitude: number | null;
  timezone: string | null;
  is_auto: boolean;
  needs_review: boolean;
}

export interface Venue {
  id: number;
  name: string;
  aliases: string[];
  city_id: number | null;
  city_name: string | null;
  region_id: number | null;
  region_name: string | null;
  country_id: number | null;
  country_code: string | null;
  country_name: string | null;
  address: string | null;
  postal_code: string | null;
  website: string | null;
  kind: string | null;
  capacity: number | null;
  is_auto: boolean;
  needs_review: boolean;
  upcoming_event_count: number | null;
  has_agenda_source: boolean;
  is_favorite: boolean;
}

export type LocationLevel = "country" | "region" | "city" | "venue";

export interface LocationRule {
  key: string;
  level: LocationLevel;
  target_id: number;
  label: string;
  context: string | null;
  country_code: string | null;
  country_name: string | null;
  description: string;
}

export interface FilterProfile {
  id: number;
  name: string;
  date_mode: "upcoming" | "months" | "range";
  months_ahead: number | null;
  date_from: string | null;
  date_to: string | null;
  include_concerts: boolean;
  include_support: boolean;
  include_special: boolean;
  festival_mode: "artist" | "always" | "never";
  festival_scope: "filters" | "anywhere";
  show_cancelled: boolean;
  show_unconfirmed: boolean;
  default_show_festivals: boolean;
  locations: LocationRule[];
}

export interface Page<T> {
  items: T[];
  total: number;
  offset: number;
  limit: number;
}

export interface Notification {
  id: number;
  type: string;
  type_label: string;
  title: string;
  body: string | null;
  artist_id: number | null;
  event_id: number | null;
  created_at: string;
  read_at: string | null;
}

export interface SearchResult {
  query: string;
  artists: Artist[];
  catalog_artists: { id: number; name: string; genre: string | null }[];
  events: TourEvent[];
  venues: Venue[];
  cities: City[];
  regions: Region[];
  countries: Country[];
}

export interface CrawlerStatusLite {
  last_run_at: string | null;
  running: number[];
  queued: number[];
}

export interface Heartbeat {
  component: string;
  kind: string;
  started_at: string;
  last_seen_at: string;
  alive: boolean;
  info: Record<string, unknown>;
}

export interface CrawlerRun {
  id: number;
  job_id: number | null;
  job_type: string;
  trigger: string;
  artist_id: number | null;
  artist_name: string | null;
  source_id: number | null;
  label: string | null;
  started_at: string;
  finished_at: string | null;
  duration_ms: number | null;
  status: "running" | "success" | "partial" | "failed";
  sources_total: number;
  sources_ok: number;
  sources_failed: number;
  events_found: number;
  events_new: number;
  events_updated: number;
  events_removed: number;
  errors_count: number;
  log?: string | null;
  summary?: Record<string, unknown>;
  errors?: CrawlerError[];
}

export interface CrawlerError {
  id: number;
  run_id: number | null;
  source_id: number | null;
  artist_id: number | null;
  artist_name: string | null;
  occurred_at: string;
  domain: string | null;
  url: string | null;
  error_type: string;
  status_code: number | null;
  message: string;
  retry_at: string | null;
}

export interface CrawlerJob {
  id: number;
  job_type: string;
  artist_id: number | null;
  artist_name: string | null;
  source_id: number | null;
  status: string;
  priority: number;
  reason: string;
  attempts: number;
  max_attempts: number;
  run_after: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  heartbeat_at: string | null;
  worker_id: string | null;
  error: string | null;
  result: Record<string, unknown> | null;
}

export interface AdminOverview {
  counts: Record<string, number>;
  crawler_status: { ok: number; partial: number; error: number; pending: number };
  recent_runs: CrawlerRun[];
  recent_errors: CrawlerError[];
  problem_sources: {
    id: number;
    name: string;
    url: string | null;
    provider: string;
    consecutive_failures: number;
    last_error: string | null;
    last_error_at: string | null;
    last_success_at: string | null;
    next_attempt_at: string | null;
  }[];
  new_events: TourEvent[];
  recent_users: { id: number; username: string; email: string; role: string; created_at: string; is_active: boolean }[];
  heartbeats: Heartbeat[];
}

export interface AuditEntry {
  id: number;
  created_at: string;
  action: string;
  actor: string | null;
  target_type?: string | null;
  target_id?: string | null;
  target: string | null;
  success: boolean;
  details: Record<string, unknown>;
  ip: string | null;
}
