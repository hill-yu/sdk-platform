import request from "@/api/request";
import type { LogLevel } from "@/api/dashboard";

export interface LogExportFilters {
  package_names: string[];
  device_id?: string;
  log_level?: LogLevel;
  date_from?: string;
  date_to?: string;
}
export type LogExportStatus = "pending" | "running" | "success" | "failed";
export interface LogExportJob {
  id: string;
  status: LogExportStatus;
  row_count: number;
  error_message?: string | null;
}

export const searchLogPackages = (keyword: string) =>
  request.get("/log-packages", { params: { keyword: keyword || undefined, limit: 20 } });
export const createLogExport = (body: LogExportFilters) => request.post("/log-exports", body);
export const getLogExport = (id: string) => request.get(`/log-exports/${id}`);
export const downloadLogExport = (id: string) =>
  request.get(`/log-exports/${id}/download`, { responseType: "blob", timeout: 60000 });
