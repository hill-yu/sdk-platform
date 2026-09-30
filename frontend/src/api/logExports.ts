import request from "@/api/request";
import type { LogLevel } from "@/api/dashboard";

export interface LogExportFilters {
  package_names: string[];
  export_mode?: "raw" | "h1";
  sdk_version?: string;
  device_id?: string;
  log_level?: LogLevel;
  date_from?: string;
  hour_from?: number;
  date_to?: string;
  hour_to?: number;
}
export type LogExportStatus = "pending" | "running" | "success" | "failed";
export interface LogExportJob {
  id: string;
  status: LogExportStatus;
  export_mode?: "raw" | "h1";
  row_count: number;
  error_message?: string | null;
}

export const searchLogPackages = (keyword: string) =>
  request.get("/log-packages", { params: { keyword: keyword || undefined, limit: 20 } });
export const createLogExport = (body: LogExportFilters) => request.post("/log-exports", body);
export const getLogExport = (id: string) => request.get(`/log-exports/${id}`);
export const downloadLogExport = (id: string) =>
  request.get(`/log-exports/${id}/download`, { responseType: "blob", timeout: 60000 });
