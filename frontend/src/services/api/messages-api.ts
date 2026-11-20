import { apiClient } from "./client";
import type {
  AIProcessingStatus,
  MessageHistoryResponse,
  MessageResponse,
  AIMessageDeliveryAccepted,
  AIMessageDeliveryStatus,
  OrchestrationAccepted,
  OrchestrationRun,
} from "../../types/api";

export const messagesApi = {
  async history(groupId: string, before?: string) {
    const { data } = await apiClient.get<MessageHistoryResponse>(`/groups/${groupId}/messages`, {
      params: { limit: 50, ...(before ? { before } : {}) },
    });
    return data;
  },
  async remove(messageId: string) {
    await apiClient.delete(`/messages/${messageId}`);
  },
  async send(groupId: string, content: string, idempotencyKey: string) {
    const { data } = await apiClient.post<MessageResponse>(
      `/groups/${groupId}/messages`,
      { content, message_type: "text" },
      { headers: { "Idempotency-Key": idempotencyKey } },
    );
    return data;
  },
  async retry(messageId: string) {
    const { data } = await apiClient.post<MessageResponse>(`/messages/${messageId}/retry`);
    return data;
  },
  async processWithAi(groupId: string, messageId: string) {
    const { data } = await apiClient.post<OrchestrationAccepted>(
      `/groups/${groupId}/messages/${messageId}/ai-process`,
    );
    return data;
  },
  async orchestration(groupId: string, orchestrationId: string) {
    const { data } = await apiClient.get<OrchestrationRun>(
      `/groups/${groupId}/orchestrations/${orchestrationId}`,
    );
    return data;
  },
  async deliver(groupId: string, orchestrationId: string) {
    const { data } = await apiClient.post<AIMessageDeliveryAccepted>(
      `/groups/${groupId}/orchestrations/${orchestrationId}/deliver`,
    );
    return data;
  },
  async deliveryStatus(groupId: string, orchestrationId: string) {
    const { data } = await apiClient.get<AIMessageDeliveryStatus>(
      `/groups/${groupId}/orchestrations/${orchestrationId}/delivery-status`,
    );
    return data;
  },
};

export type { AIProcessingStatus, MessageResponse };
