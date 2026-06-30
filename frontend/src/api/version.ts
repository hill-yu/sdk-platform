import request from "@/api/request";

export const getVersions = (params: Record<string, unknown>) => request.get("/versions", { params });
export const createVersion = (data: Record<string, unknown>) => request.post("/versions", data);
export const updateVersion = (id: number, data: Record<string, unknown>) => request.put(`/versions/${id}`, data);
