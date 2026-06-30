import axios from "axios";

const request = axios.create({
  baseURL: "/api/admin",
  timeout: 10000,
});

request.interceptors.request.use((config) => {
  const token = window.localStorage.getItem("admin_token") || import.meta.env.VITE_ADMIN_TOKEN || "";
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  } else if (config.headers.Authorization) {
    delete config.headers.Authorization;
  }
  return config;
});

request.interceptors.response.use(
  (response) => response.data,
  (error) => {
    const message = error?.response?.data?.detail || error?.message || "Request failed";
    return Promise.reject(new Error(message));
  }
);

export default request;
