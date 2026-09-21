import request from "@/api/request";

export type LogLevel = "debug" | "info" | "warn" | "error";

export interface EventFilterOptions {
  package_names: string[];
  sdk_versions: string[];
}

export interface EventItem {
  id: number;
  event_type: string;
  package_name: string;
  device_id?: string | null;
  sdk_version?: string | null;
  payload: Record<string, unknown>;
  client_ts?: string | null;
  server_ts: string;
}

export interface EventQuery {
  page: number;
  page_size: number;
  event_type?: string;
  package_name?: string;
  sdk_version?: string;
  device_id?: string;
  log_level?: LogLevel;
  date_from?: string;
  date_to?: string;
}

export const getSummary = () => request.get("/dashboard/summary");
export const getTrend = (params: Record<string, unknown>) => request.get("/dashboard/trend", { params });
export const getBreakdown = (params: Record<string, unknown>) =>
  request.get("/dashboard/breakdown", { params });
export const getEvents = (params: EventQuery) => request.get("/events", { params });
export const getEventFilterOptions = (packageName?: string) =>
  request.get("/events/filter-options", {
    params: { package_name: packageName || undefined },
  });
