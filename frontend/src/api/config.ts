import request from "@/api/request";

export const getConfigs = (packageName?: string) => request.get("/configs", { params: { package_name: packageName || undefined } });
export const getConfig = (id: number) => request.get(`/configs/${id}`);
export const createConfig = (data: Record<string, unknown>) => request.post("/configs", data);
export const updateConfig = (id: number, data: Record<string, unknown>) => request.put(`/configs/${id}`, data, { timeout: 60_000 });
export const publishConfig = (id: number) => request.post(`/configs/${id}/publish`, undefined, { timeout: 60_000 });
export const rollbackConfig = (id: number) => request.post(`/configs/${id}/rollback`);
