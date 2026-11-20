import { apiClient } from "./client";
import type { LoginResponse, RegisterRequest, UserProfile } from "../../types/api";

export const authApi = {
  async login(payload: { email: string; password: string }) {
    const { data } = await apiClient.post<LoginResponse>("/auth/login", payload);
    return data;
  },
  async register(payload: RegisterRequest) {
    const { data } = await apiClient.post<UserProfile>("/auth/register", payload);
    return data;
  },
  async me() {
    const { data } = await apiClient.get<UserProfile>("/auth/me");
    return data;
  },
  async logout() {
    await apiClient.post("/auth/logout");
  },
};
