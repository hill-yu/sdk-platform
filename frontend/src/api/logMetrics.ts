import request from "@/api/request";

export type ParseJobStatus = "pending" | "running" | "success" | "failed" | "cancelled";
export interface LogMetricScope { package_name: string; date_from: string; hour_from: number; date_to: string; hour_to: number; }
export interface ParseJob extends LogMetricScope {
  id: number; range_start: string; range_end: string; snapshot_end?: string; status: ParseJobStatus;
  total_count: number; processed_count: number; h1_count: number; failed_h1_count: number; no_h1_count: number;
  cursor_event_id?: number | null; cursor_server_ts?: string | null; error_summary?: string | null;
}
export type RawTargetKind = "banner" | "anchored" | "web_element" | string;
export interface TargetMetric { target_kind: RawTargetKind; planned_count: number; actual_count: number; success_count: number; failure_count: number; actual_rate: number | null; success_rate: number | null; failure_rate: number | null; }
export interface MetricOverview {
  declaration_count: number; planned_click_count: number; actual_click_count: number; response_success_count: number;
  plan_mismatch_count: number; interstitial_presentation_count: number; interstitial_click_count: number;
  interstitial_close_count: number; interstitial_close_rate: number | null; interstitial_non_close_click_rate: number | null;
  target_breakdown: Record<string, TargetMetric>;
}
export interface ConfigMetricItem { config_id: number | "unknown"; declaration_count: number; share: number | null; }
export interface FailureBreakdownItem { failure_category: string; failure_count: number; share: number | null; }
export interface H1Detail { event_id: number; event_server_ts: string; record_index: number; package_name: string; device_id: string | null; sdk_version: string | null; config_id: number | null; declared_click_count: number | null; status: string; click_attempts: Array<Record<string, unknown>>; }
export interface ApiEnvelope<T> { code: number; data: T; }
export interface Paginated<T> { total: number; page: number; page_size: number; items: T[]; }

export const postParseJob = (scope: LogMetricScope) => request.post<ApiEnvelope<ParseJob>>("/log-analysis/parse-jobs", scope);
export const getParseJob = (id: number) => request.get<ApiEnvelope<ParseJob>>(`/log-analysis/parse-jobs/${id}`);
export const cancelParseJob = (id: number) => request.post<ApiEnvelope<ParseJob>>(`/log-analysis/parse-jobs/${id}/cancel`);
export const getMetricOverview = (scope: LogMetricScope) => request.get<ApiEnvelope<MetricOverview>>("/log-analysis/metrics/overview", { params: scope });
export const getMetricConfigs = (scope: LogMetricScope) => request.get<ApiEnvelope<{ total: number; items: ConfigMetricItem[] }>>("/log-analysis/metrics/configs", { params: scope });
export const getMetricTargets = (scope: LogMetricScope) => request.get<ApiEnvelope<{ items: TargetMetric[] }>>("/log-analysis/metrics/targets", { params: scope });
export const getMetricFailures = (scope: LogMetricScope & { target_kind?: "web_element" | "ad_area"; config_id?: number }) => request.get<ApiEnvelope<FailureBreakdownItem[]>>("/log-analysis/metrics/failures", { params: scope });
export const getH1Details = (scope: LogMetricScope & { page: number; page_size: number; sort_order?: "asc" | "desc" }) => request.get<ApiEnvelope<Paginated<H1Detail>>>("/log-analysis/metrics/h1", { params: scope });
