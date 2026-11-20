import { apiClient } from "./client";
import type {
  ConnectionActionResponse,
  ConnectionRequest,
  Page,
  PublicUserProfile,
} from "../../types/api";

export const connectionsApi = {
  async list() {
    const { data } = await apiClient.get<Page<PublicUserProfile>>("/connections", {
      params: { limit: 100, offset: 0 },
    });
    return data;
  },
  async incoming() {
    const { data } = await apiClient.get<Page<ConnectionRequest>>("/connections/requests/incoming", {
      params: { limit: 100, offset: 0 },
    });
    return data;
  },
  async outgoing() {
    const { data } = await apiClient.get<Page<ConnectionRequest>>("/connections/requests/outgoing", {
      params: { limit: 100, offset: 0 },
    });
    return data;
  },
  async send(recipientId: string) {
    const { data } = await apiClient.post<ConnectionActionResponse>("/connections/requests", {
      recipient_id: recipientId,
    });
    return data;
  },
  async accept(requestId: string) {
    const { data } = await apiClient.post<ConnectionActionResponse>(
      `/connections/requests/${requestId}/accept`,
    );
    return data;
  },
  async reject(requestId: string) {
    const { data } = await apiClient.post<ConnectionActionResponse>(
      `/connections/requests/${requestId}/reject`,
    );
    return data;
  },
  async cancel(requestId: string) {
    await apiClient.delete(`/connections/requests/${requestId}`);
  },
  async remove(userId: string) {
    await apiClient.delete(`/connections/${userId}`);
  },
};
