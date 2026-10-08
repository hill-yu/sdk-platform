import request from "@/api/request";

export interface UsageScope { package_name?: string; date_from: string; hour_from: number; date_to: string; hour_to: number; }
export interface DurationBucket { key: "le_300" | "301_600" | "601_899" | "ge_900"; count: number; share: number | null; }
export interface UsageSummaryItem { package_name: string; device_model: string | null; device_count: number; total_duration_s: number; average_duration_s: number | null; buckets: DurationBucket[]; last_report_at: string | null; }
export interface UsageDevice { package_name: string; device_id: string; device_model: string | null; duration_s: number; sdk_version: string | null; app_version: string | null; last_report_at: string | null; }
export interface UsagePage<T> { total: number; page: number; page_size: number; items: T[]; }

export const getUsageSummary = (scope: UsageScope & { page?: number; page_size?: number; sort_by?: string; sort_order?: "asc" | "desc" }) =>
  request.get<{ code: number; data: UsagePage<UsageSummaryItem> }>("/usage-durations/summary", { params: scope });
export const getUsageDevices = (scope: UsageScope & { package_name: string; device_model?: string | null; page?: number; page_size?: number }) =>
  request.get<{ code: number; data: UsagePage<UsageDevice> }>("/usage-durations/devices", { params: scope });
