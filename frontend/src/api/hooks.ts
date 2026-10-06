// React Query hooks for all TourDesk endpoints.
import { useMutation, useQuery, useQueryClient, keepPreviousData } from "@tanstack/react-query";
import { api } from "./client";
import type {
  AdminOverview,
  AdminUser,
  Artist,
  ArtistEvents,
  ArtistSources,
  AuditEntry,
  City,
  Country,
  CrawlerError,
  CrawlerJob,
  CrawlerRun,
  CrawlerStatusLite,
  Dashboard,
  EventDetail,
  Explanation,
  FilterProfile,
  LocationRule,
  LookupItem,
  Me,
  Notification,
  Page,
  Region,
  SearchResult,
  Settings,
  SettingsOptions,
  SetupStatus,
  Source,
  TourEvent,
  Venue,
} from "./types";

export const qk = {
  me: ["me"] as const,
  dashboard: ["dashboard"] as const,
  artists: ["artists"] as const,
  artist: (id: number) => ["artist", id] as const,
  artistEvents: (id: number) => ["artist", id, "events"] as const,
  artistSources: (id: number) => ["artist", id, "sources"] as const,
  event: (id: number) => ["event", id] as const,
  filter: ["filter"] as const,
  notifications: ["notifications"] as const,
};

export function useSetupStatus() {
  return useQuery({ queryKey: ["setup-status"], queryFn: () => api.get<SetupStatus>("/api/auth/setup-status"), staleTime: 10_000 });
}

export function useMe(enabled = true) {
  return useQuery({ queryKey: qk.me, queryFn: () => api.get<Me>("/api/auth/me"), retry: false, enabled, staleTime: 60_000 });
}

export function useSettingsOptions() {
  return useQuery({ queryKey: ["settings-options"], queryFn: () => api.get<SettingsOptions>("/api/settings/options"), staleTime: Infinity });
}

export function useUpdateSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (patch: Partial<Settings>) => api.put<Settings>("/api/settings", patch),
    onSuccess: (settings) => {
      qc.setQueryData<Me>(qk.me, (me) => (me ? { ...me, settings } : me));
    },
  });
}

export function useDashboard() {
  return useQuery({
    queryKey: qk.dashboard,
    queryFn: () => api.get<Dashboard>("/api/dashboard"),
    refetchInterval: 120_000,
    staleTime: 20_000,
  });
}

export function useArtists() {
  return useQuery({ queryKey: qk.artists, queryFn: () => api.get<Artist[]>("/api/artists"), staleTime: 30_000 });
}

export function useArtist(id: number) {
  return useQuery({ queryKey: qk.artist(id), queryFn: () => api.get<Artist>(`/api/artists/${id}`) });
}

export function useArtistEvents(id: number, enabled = true) {
  return useQuery({ queryKey: qk.artistEvents(id), queryFn: () => api.get<ArtistEvents>(`/api/artists/${id}/events`), enabled });
}

export function useArtistSources(id: number, enabled = true) {
  return useQuery({ queryKey: qk.artistSources(id), queryFn: () => api.get<ArtistSources>(`/api/artists/${id}/sources`), enabled });
}

export function useInvalidateArtistData() {
  const qc = useQueryClient();
  return (artistId?: number) => {
    qc.invalidateQueries({ queryKey: qk.dashboard });
    qc.invalidateQueries({ queryKey: qk.artists });
    if (artistId) qc.invalidateQueries({ queryKey: ["artist", artistId] });
    qc.invalidateQueries({ queryKey: ["events"] });
  };
}

export function useUpdateArtist(id: number) {
  const invalidate = useInvalidateArtistData();
  return useMutation({
    mutationFn: (patch: Record<string, unknown>) => api.patch<Artist>(`/api/artists/${id}`, patch),
    onSuccess: () => invalidate(id),
  });
}

export function useEvent(id: number) {
  return useQuery({ queryKey: qk.event(id), queryFn: () => api.get<EventDetail>(`/api/events/${id}`) });
}

export function useAdminEvent(id: number, userId?: number | null) {
  return useQuery({
    queryKey: ["admin-event", id, userId ?? null],
    queryFn: () => api.get<EventDetail>(`/api/admin/events/${id}`, { user_id: userId ?? undefined }),
  });
}

export function useExplain(id: number) {
  return useQuery({ queryKey: ["explain", id], queryFn: () => api.get<Explanation>(`/api/events/${id}/explain`) });
}

export function useEvents(params: Record<string, unknown>) {
  return useQuery({
    queryKey: ["events", params],
    queryFn: () => api.get<Page<TourEvent>>("/api/events", params),
    placeholderData: keepPreviousData,
  });
}

export function useFilter() {
  return useQuery({ queryKey: qk.filter, queryFn: () => api.get<FilterProfile>("/api/filters") });
}

export function useFilterMutations() {
  const qc = useQueryClient();
  const refresh = () => {
    qc.invalidateQueries({ queryKey: qk.filter });
    qc.invalidateQueries({ queryKey: qk.dashboard });
    qc.invalidateQueries({ queryKey: ["artist"] });
    qc.invalidateQueries({ queryKey: ["events"] });
    qc.invalidateQueries({ queryKey: ["venues"] });
  };
  return {
    update: useMutation({ mutationFn: (patch: Partial<FilterProfile>) => api.put<FilterProfile>("/api/filters", patch), onSuccess: refresh }),
    add: useMutation({
      mutationFn: (rule: { level: string; target_id: number }) => api.post<LocationRule[]>("/api/filters/locations", rule),
      onSuccess: refresh,
    }),
    remove: useMutation({ mutationFn: (key: string) => api.del<LocationRule[]>(`/api/filters/locations/${key}`), onSuccess: refresh }),
  };
}

export function useCountries() {
  return useQuery({ queryKey: ["countries"], queryFn: () => api.get<Country[]>("/api/countries"), staleTime: Infinity });
}

export function useRegions(countryId: number | null, q = "") {
  return useQuery({
    queryKey: ["regions", countryId, q],
    queryFn: () => api.get<Region[]>("/api/regions", { country_id: countryId ?? undefined, q }),
    enabled: countryId !== null || q.length >= 2,
    staleTime: 300_000,
  });
}

export function useCities(params: { q?: string; country_id?: number | null; region_id?: number | null; limit?: number }, enabled = true) {
  return useQuery({
    queryKey: ["cities", params],
    queryFn: () => api.get<City[]>("/api/cities", params),
    enabled,
    staleTime: 60_000,
    placeholderData: keepPreviousData,
  });
}

export function useVenues(params: { q?: string; city_id?: number | null; country_id?: number | null; favorites?: boolean; limit?: number }, enabled = true) {
  return useQuery({
    queryKey: ["venues", params],
    queryFn: () => api.get<Venue[]>("/api/venues", params),
    enabled,
    staleTime: 30_000,
    placeholderData: keepPreviousData,
  });
}

export function useLookup(q: string, external: boolean) {
  return useQuery({
    queryKey: ["lookup", q, external],
    queryFn: () => api.get<LookupItem[]>("/api/artists/lookup", { q, external }),
    enabled: q.trim().length >= 2,
    staleTime: 60_000,
  });
}

export function useSearch(q: string) {
  return useQuery({
    queryKey: ["search", q],
    queryFn: () => api.get<SearchResult>("/api/search", { q }),
    enabled: q.trim().length >= 2,
    staleTime: 15_000,
    placeholderData: keepPreviousData,
  });
}

export function useNotifications(enabled = true) {
  return useQuery({
    queryKey: qk.notifications,
    queryFn: () => api.get<{ items: Notification[]; unread: number }>("/api/notifications"),
    refetchInterval: 60_000,
    enabled,
  });
}

export function useCrawlerStatus() {
  return useQuery({
    queryKey: ["crawler-status"],
    queryFn: () => api.get<CrawlerStatusLite>("/api/crawler/status"),
    refetchInterval: (query) => {
      const data = query.state.data;
      return data && (data.running.length || data.queued.length) ? 5_000 : 30_000;
    },
  });
}

// ----------------------------------------------------------------------------- admin
export function useAdminOverview() {
  return useQuery({ queryKey: ["admin", "overview"], queryFn: () => api.get<AdminOverview>("/api/admin/overview"), refetchInterval: 30_000 });
}

export function useAdminUsers(q = "") {
  return useQuery({ queryKey: ["admin", "users", q], queryFn: () => api.get<AdminUser[]>("/api/admin/users", { q }) });
}

export function useAdminRuns(params: Record<string, unknown>) {
  return useQuery({
    queryKey: ["admin", "runs", params],
    queryFn: () => api.get<{ total: number; items: CrawlerRun[] }>("/api/admin/crawler/runs", params),
    refetchInterval: 15_000,
    placeholderData: keepPreviousData,
  });
}

export function useAdminErrors(params: Record<string, unknown>) {
  return useQuery({
    queryKey: ["admin", "errors", params],
    queryFn: () => api.get<{ total: number; by_type: Record<string, number>; items: CrawlerError[] }>("/api/admin/crawler/errors", params),
    placeholderData: keepPreviousData,
  });
}

export function useAdminJobs(params: Record<string, unknown>) {
  return useQuery({
    queryKey: ["admin", "jobs", params],
    queryFn: () => api.get<{ total: number; items: CrawlerJob[] }>("/api/admin/crawler/jobs", params),
    refetchInterval: 5_000,
    placeholderData: keepPreviousData,
  });
}

export function useAdminSources(params: Record<string, unknown>) {
  return useQuery({
    queryKey: ["admin", "sources", params],
    queryFn: () => api.get<{ total: number; items: Source[]; providers: Record<string, string> }>("/api/admin/sources", params),
    placeholderData: keepPreviousData,
  });
}

export function useAdminAudit(params: Record<string, unknown>) {
  return useQuery({
    queryKey: ["admin", "audit", params],
    queryFn: () => api.get<{ total: number; items: AuditEntry[] }>("/api/admin/audit", params),
    placeholderData: keepPreviousData,
  });
}
