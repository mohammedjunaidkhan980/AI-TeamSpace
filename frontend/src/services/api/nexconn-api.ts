import { apiClient } from "./client";

export interface NexconnTokenResponse {
  nexconn_token: string;
  nexconn_user_id: string;
  app_key: string;
}

export interface NexconnStatusResponse {
  enabled: boolean;
  status: "enabled" | "disabled";
}

export const nexconnApi = {
  async token() {
    const { data } = await apiClient.post<NexconnTokenResponse>("/nexconn/token");
    return data;
  },
  async status() {
    const { data } = await apiClient.get<NexconnStatusResponse>("/nexconn/status");
    return data;
  },
};
