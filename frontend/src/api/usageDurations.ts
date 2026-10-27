import request from "@/api/request";

export interface UsageScope { package_name?: string; date_from: string; hour_from: number; date_to: string; hour_to: number; }
export interface DurationBucket { key: "le_120" | "121_300" | "301_600" | "601_899" | "900_1199" | "1200_1499" | "ge_1500"; count: number; count_text: string; share: number | null; share_text: string; total_duration_s: number; total_duration_text: string; total_duration_exact_text: string; interval_text: string; }
export interface UsageSummaryItem { package_name: string; device_model: string | null; device_count: number; total_duration_s: number; total_duration_text: string; total_duration_exact_text: string; average_duration_s: number | null; average_duration_text: string; average_duration_exact_text: string; buckets: DurationBucket[]; last_report_at: string | null; last_report_text: string; }
export interface UsageDevice { package_name: string; device_id: string; device_model: string | null; os: string | null; duration_s: number | null; duration_text: string; duration_exact_text: string; sdk_version: string | null; app_version: string | null; last_report_at: string | null; last_report_text: string; }
export interface UsagePage<T> { total: number; total_pages: number; page: number; page_size: number; items: T[]; }

export const getUsageSummary = (scope: UsageScope & { page?: number; page_size?: number; sort_by?: string; sort_order?: "asc" | "desc" }) =>
  request.get<{ code: number; data: UsagePage<UsageSummaryItem> }>("/usage-durations/summary", { params: scope });
export const getUsageDevices = (scope: UsageScope & { package_name: string; device_model?: string | null; page?: number; page_size?: number }) =>
  request.get<{ code: number; data: UsagePage<UsageDevice> }>("/usage-durations/devices", { params: scope });

export const searchUsagePackages = (keyword: string) =>
  request.get<{ code: number; data: { items: string[] } }>("/usage-package-names", { params: { keyword: keyword || undefined, limit: 20 } }) as unknown as Promise<{ code: number; data: { items: string[] } }>;
