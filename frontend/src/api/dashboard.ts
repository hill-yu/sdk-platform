import request from "@/api/request";

export const getSummary = () => request.get("/dashboard/summary");
export const getTrend = (params: Record<string, unknown>) => request.get("/dashboard/trend", { params });
export const getBreakdown = (params: Record<string, unknown>) =>
  request.get("/dashboard/breakdown", { params });
export const getEvents = (params: Record<string, unknown>) => request.get("/events", { params });
