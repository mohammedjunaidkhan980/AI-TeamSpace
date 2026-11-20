import { apiClient } from "./client";
import type { NotificationListResponse } from "../../types/api";

export const notificationsApi = {
  async list(before?: string) {
    const { data } = await apiClient.get<NotificationListResponse>("/notifications", {
      params: { limit: 30, ...(before ? { before } : {}) },
    });
    return data;
  },
  async unreadCount() {
    const { data } = await apiClient.get<{ unread_count: number }>("/notifications/unread-count");
    return data;
  },
  async read(notificationId: string) {
    await apiClient.put(`/notifications/${notificationId}/read`);
  },
  async readAll() {
    const { data } = await apiClient.put<{ updated_count: number }>("/notifications/read-all");
    return data;
  },
  async remove(notificationId: string) {
    await apiClient.delete(`/notifications/${notificationId}`);
  },
};
