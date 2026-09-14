import request from "@/api/request";

export type LogLevel = "debug" | "info" | "warn" | "error";
export type DecodeStatus = "pending" | "success" | "unsupported" | "failed";
export type ReparseJobStatus = "pending" | "running" | "success" | "failed" | "cancelled";
export type LogColumnDefinition = string;

export interface ApiEnvelope<T> {
  code: number;
  data: T;
}

export interface PaginatedResponse<T> {
  total: number;
  page: number;
  page_size: number;
  items: T[];
}

export interface LogAnalysisSummaryItem {
  date: string;
  package_name: string;
  alias: string;
  company: string;
  account: string;
  primary_url: string | null;
  url_count: number;
  user_count: number;
  flow_count: number;
  expected_click_count: number;
  actual_click_count: number;
  ad_click_count: number;
  interstitial_presentation_count: number;
  interstitial_click_count: number;
  average_duration_ms: number | null;
  duration_sample_count: number;
  success_rate: number | null;
  success_sample_count: number;
  failed_count: number;
  unsupported_count: number;
  parse_failure_count: number;
}

export interface LogDecodeItem {
  event_id: number;
  event_server_ts: string;
  record_index: number;
  package_name: string;
  device_id: string | null;
  status: DecodeStatus;
  decoder_version: string;
  decoded_timestamp: string | null;
  url: string | null;
  config_id: number | null;
  window: string | null;
  expected_click_count: number | null;
  actual_click_count: number | null;
  ad_click_count: number | null;
  interstitial_presentation_count: number | null;
  interstitial_click_count: number | null;
  interstitial_close_count: number | null;
  duration_ms: number | null;
  final_reason: string | null;
  is_success: boolean | null;
  decoded_payload: unknown;
  parse_error: string | null;
  parsed_at: string | null;
  extra?: string | null;
}

export interface PackageProfile {
  package_name: string;
  alias: string;
  company: string;
  account: string;
}

export type PackageProfilePayload = Partial<Omit<PackageProfile, "package_name">>;

export interface LogAnalysisColumns {
  available_columns: LogColumnDefinition[];
  default_columns: LogColumnDefinition[];
  columns: LogColumnDefinition[];
}

export interface SummaryQuery {
  date_from?: string;
  date_to?: string;
  package_name?: string;
  device_id?: string;
  log_level?: LogLevel;
  page: number;
  page_size: number;
  sort_by?: string;
  sort_order?: "asc" | "desc";
}

export interface DetailsQuery {
  date: string;
  package_name: string;
  page: number;
  page_size: number;
  device_id?: string;
  log_level?: LogLevel;
  status?: DecodeStatus;
  sort_by?: string;
  sort_order?: "asc" | "desc";
}

export interface DetailKey {
  event_server_ts: string;
  record_index: number;
}

export interface ReparsePayload {
  date_from?: string;
  date_to?: string;
  package_name?: string;
  status?: DecodeStatus;
  decoder_version_before?: string;
}

export interface ReparseJob {
  id: number;
  package_name: string | null;
  range_start: string;
  range_end: string;
  cursor_event_id: number | null;
  cursor_server_ts: string | null;
  processed_count: number;
  decoded_count: number;
  failed_count: number;
  status: ReparseJobStatus;
}

export const getLogAnalysisSummary = (params: SummaryQuery) =>
  request.get<ApiEnvelope<PaginatedResponse<LogAnalysisSummaryItem>>>("/log-analysis/summary", { params });

export const getLogAnalysisDetails = (params: DetailsQuery) =>
  request.get<ApiEnvelope<PaginatedResponse<LogDecodeItem>>>("/log-analysis/details", { params });

export const getLogAnalysisDetail = (eventId: number, params: DetailKey) =>
  request.get<ApiEnvelope<LogDecodeItem>>(`/log-analysis/details/${eventId}`, { params });

export const getPackageProfile = (packageName: string) =>
  request.get<ApiEnvelope<PackageProfile>>("/package-profiles", { params: { package_name: packageName } });

export const putPackageProfile = (packageName: string, payload: PackageProfilePayload) =>
  request.put<ApiEnvelope<PackageProfile>>(`/package-profiles/${packageName}`, payload);

export const getLogAnalysisColumns = () =>
  request.get<ApiEnvelope<LogAnalysisColumns>>("/log-analysis/columns");

export const putLogAnalysisColumns = (payload: Pick<LogAnalysisColumns, "columns">) =>
  request.put<ApiEnvelope<LogAnalysisColumns>>("/log-analysis/columns", payload);

export const postLogReparse = (payload: ReparsePayload) =>
  request.post<ApiEnvelope<ReparseJob>>("/log-analysis/reparse", payload);
