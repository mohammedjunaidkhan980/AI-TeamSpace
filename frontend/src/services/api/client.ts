import axios from "axios";
import { useAuthStore } from "../../stores/auth-store";

const apiOrigin = (import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000").replace(/\/+$/, "");

export const apiClient = axios.create({
  baseURL: `${apiOrigin}/api/v1`,
  headers: { "Content-Type": "application/json" },
  timeout: 20_000,
});

apiClient.interceptors.request.use((config) => {
  const { accessToken, tokenExpiresAt, clearSession } = useAuthStore.getState();
  if (accessToken && tokenExpiresAt !== null && tokenExpiresAt <= Date.now()) {
    clearSession();
    if (window.location.pathname !== "/login" && window.location.pathname !== "/register") {
      window.location.assign("/login");
    }
    return Promise.reject(new Error("Your session has expired. Please sign in again."));
  }
  const token = accessToken;
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

apiClient.interceptors.response.use(
  (response) => response,
  (error: unknown) => {
    if (axios.isAxiosError(error) && error.response?.status === 401) {
      useAuthStore.getState().clearSession();
      if (window.location.pathname !== "/login" && window.location.pathname !== "/register") {
        window.location.assign("/login");
      }
    }
    return Promise.reject(error);
  },
);
