import axios from "axios";

const request = axios.create({
  baseURL: "/api/admin",
  timeout: 10000,
});

const getToken = (): string => {
  // 优先从 sessionStorage 读取
  const stored = sessionStorage.getItem("admin_token");
  if (stored) return stored;
  // 弹出输入框
  const input = prompt("请输入 Admin Token:");
  if (input) {
    sessionStorage.setItem("admin_token", input);
    return input;
  }
  return "";
};

request.interceptors.request.use((config) => {
  const token = getToken();
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
