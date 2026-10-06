// Admin-only queries and mutations.
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, errorMessage } from "../../api/client";
import type { AdminUser, Artist, AuditEntry, City, CrawlerError, CrawlerJob, CrawlerRun, FilterProfile, Heartbeat, Page, TourEvent, Venue } from "../../api/types";
import { toast } from "../../state/ui";

export interface CrawlerStatusFull {
  queue: { status: string; job_type: string; count: number }[];
  running: CrawlerJob[];
  runs_24h: Record<string, number>;
  heartbeats: Heartbeat[];
  next_due: string | null;
  settings: CrawlerSettings;
}

export interface CrawlerSettings {
  enabled: boolean;
  interval_minutes: number;
  user_agent: string;
  contact: string;
  respect_robots: boolean;
  min_domain_interval_s: number;
  timeout_s: number;
  max_retries: number;
  max_response_mb: number;
  cache_ttl_minutes: number;
  max_pages_per_source: number;
  allow_private_networks: boolean;
  worker_threads: number;
  enrich_interval_days: number;
  source_backoff_max_hours: number;
  geocoder_enabled: boolean;
  geocoder_url: string;
  musicbrainz_lookup: boolean;
  image_providers: string[];
  ticketmaster_countries: string[];
  keep_runs_days: number;
  providers: Record<string, boolean>;
  api_keys: Record<string, string>;
  api_keys_from_env: Record<string, boolean>;
}

export interface SystemInfo {
  version: string;
  python: string;
  platform: string;
  env: string;
  public_url: string | null;
  trusted_proxies: string[] | string;
  cookie_secure: string | boolean | null;
  frontend: string | null;
  database: Record<string, unknown>;
  disk: { total: number; used: number; free: number; media_bytes: number };
  counts: Record<string, number>;
  heartbeats: Heartbeat[];
  logs: { name: string; exists: boolean; size: number }[];
}

export interface CrawlerDomain {
  domain: string;
  last_request_at: string | null;
  request_count: number;
  error_count: number;
  last_error: string | null;
  crawl_delay_s: number | null;
  robots_status: string | null;
  robots_fetched_at: string | null;
  blocked_until: string | null;
}

export const useAdminSystem = () => useQuery({ queryKey: ["admin", "system"], queryFn: () => api.get<SystemInfo>("/api/admin/system"), refetchInterval: 30_000 });

export const useAdminLogs = (params: { file: string; level?: string; q?: string; lines?: number }) =>
  useQuery({
    queryKey: ["admin", "logs", params],
    queryFn: () => api.get<{ file: string; entries: Record<string, unknown>[] }>("/api/admin/logs", params),
    refetchInterval: 10_000,
    placeholderData: keepPreviousData,
  });

export const useAdminCrawlerStatus = () =>
  useQuery({ queryKey: ["admin", "crawler-status"], queryFn: () => api.get<CrawlerStatusFull>("/api/admin/crawler/status"), refetchInterval: 5_000 });

export const useAdminRun = (id: number | null) =>
  useQuery({ queryKey: ["admin", "run", id], queryFn: () => api.get<CrawlerRun>(`/api/admin/crawler/runs/${id}`), enabled: id !== null });

export const useAdminJob = (id: number | null) =>
  useQuery({
    queryKey: ["admin", "job", id],
    queryFn: () => api.get<CrawlerJob>(`/api/admin/crawler/jobs/${id}`),
    enabled: id !== null,
    refetchInterval: (q) => (q.state.data && ["queued", "running"].includes(q.state.data.status) ? 1500 : false),
  });

export const useAdminCrawlerSettings = () => useQuery({ queryKey: ["admin", "crawler-settings"], queryFn: () => api.get<CrawlerSettings>("/api/admin/crawler/settings") });

export const useAdminDomains = (enabled: boolean) =>
  useQuery({ queryKey: ["admin", "domains"], queryFn: () => api.get<CrawlerDomain[]>("/api/admin/crawler/domains"), enabled, refetchInterval: 20_000 });

export const useAdminUser = (id: number | null) => useQuery({ queryKey: ["admin", "user", id], queryFn: () => api.get<AdminUser>(`/api/admin/users/${id}`), enabled: id !== null });

export const useAdminUserArtists = (id: number | null) =>
  useQuery({ queryKey: ["admin", "user", id, "artists"], queryFn: () => api.get<Artist[]>(`/api/admin/users/${id}/artists`), enabled: id !== null });

export const useAdminUserFilters = (id: number | null) =>
  useQuery({ queryKey: ["admin", "user", id, "filters"], queryFn: () => api.get<FilterProfile>(`/api/admin/users/${id}/filters`), enabled: id !== null });

export const useAdminUserAudit = (id: number | null) =>
  useQuery({ queryKey: ["admin", "user", id, "audit"], queryFn: () => api.get<AuditEntry[]>(`/api/admin/users/${id}/audit`), enabled: id !== null });

export const useAdminEventsList = (params: Record<string, unknown>) =>
  useQuery({
    queryKey: ["admin", "events", params],
    queryFn: () => api.get<{ total: number; items: TourEvent[] }>("/api/admin/events", params),
    placeholderData: keepPreviousData,
  });

export const useAdminCatalog = (params: Record<string, unknown>) =>
  useQuery({
    queryKey: ["admin", "catalog", params],
    queryFn: () => api.get<{ total: number; items: Artist[] }>("/api/admin/artists", params),
    placeholderData: keepPreviousData,
  });

export const useAdminGeoReview = () =>
  useQuery({ queryKey: ["admin", "geo-review"], queryFn: () => api.get<{ cities: City[]; venues: Venue[] }>("/api/admin/geo/review") });

export type { Page, CrawlerError };

/** Mutation helper: runs, shows a toast and refreshes all admin queries. */
export function useAdminAction<TArgs = void, TResult = unknown>(fn: (args: TArgs) => Promise<TResult>, success?: string | ((r: TResult) => string)) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: (r) => {
      const msg = typeof success === "function" ? success(r) : success;
      if (msg) toast(msg, "success");
      qc.invalidateQueries({ queryKey: ["admin"] });
    },
    onError: (e) => toast(errorMessage(e), "error"),
  });
}
