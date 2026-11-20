import { apiClient } from "./client";
import type { Page, PublicUserProfile, UserProfile } from "../../types/api";

export const usersApi = {
  async search(query: string) {
    const { data } = await apiClient.get<Page<PublicUserProfile>>("/users/search", {
      params: { q: query, limit: 20, offset: 0 },
    });
    return data;
  },
  async me() {
    const { data } = await apiClient.get<UserProfile>("/users/me");
    return data;
  },
  async updateMe(payload: Partial<Pick<UserProfile, "username" | "full_name">> & { bio?: string | null; status_message?: string | null }) {
    const { data } = await apiClient.put<UserProfile>("/users/me", payload);
    return data;
  },
};
