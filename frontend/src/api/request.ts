import axios from "axios";
import { clearAdminSession, getCsrfToken } from "@/stores/adminAuth";

const request = axios.create({
  baseURL: "/api/admin",
  timeout: 10000,
  withCredentials: true,
});

request.interceptors.request.use((config) => {
  const method = (config.method || "get").toUpperCase();
  const csrf = getCsrfToken();
  if (csrf && ["POST", "PUT", "PATCH", "DELETE"].includes(method)) {
    config.headers["X-CSRF-Token"] = csrf;
  }
  return config;
});

request.interceptors.response.use(
  (response) => response.data,
  (error) => {
    if (error?.response?.status === 401 && !String(error?.config?.url || "").includes("/auth/")) {
      clearAdminSession();
      window.dispatchEvent(new CustomEvent("admin-auth-expired"));
    }
    const message = error?.response?.data?.detail || error?.message || "Request failed";
    error.message = message;
    return Promise.reject(error);
  }
);

export default request;
