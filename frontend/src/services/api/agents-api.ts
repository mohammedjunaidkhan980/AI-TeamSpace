import { apiClient } from "./client";
import type { AgentTemplate, GroupAgent, GroupAgentListResponse } from "../../types/api";

export const agentsApi = {
  async templates() {
    const { data } = await apiClient.get<AgentTemplate[]>("/agents/templates");
    return data;
  },
  async groupAgents(groupId: string) {
    const { data } = await apiClient.get<GroupAgentListResponse>(`/groups/${groupId}/agents`);
    return data.items;
  },
  async addToGroup(groupId: string, templateId: string) {
    const { data } = await apiClient.post<GroupAgent>(`/groups/${groupId}/agents`, {
      template_id: templateId,
    });
    return data;
  },
  async updateStatus(groupId: string, agentId: string, enabled: boolean) {
    const { data } = await apiClient.patch<GroupAgent>(
      `/groups/${groupId}/agents/${agentId}/status`,
      { enabled },
    );
    return data;
  },
  async removeFromGroup(groupId: string, agentId: string) {
    await apiClient.delete(`/groups/${groupId}/agents/${agentId}`);
  },
};
