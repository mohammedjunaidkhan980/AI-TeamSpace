import { apiClient } from "./client";
import type {
  AddGroupMembersResponse,
  GroupDetails,
  GroupListResponse,
  GroupMessageStats,
  GroupMember,
} from "../../types/api";

export const groupsApi = {
  async list() {
    const { data } = await apiClient.get<GroupListResponse>("/groups", {
      params: { limit: 100, offset: 0 },
    });
    return data;
  },
  async get(groupId: string) {
    const { data } = await apiClient.get<GroupDetails>(`/groups/${groupId}`);
    return data;
  },
  async create(payload: { name: string; description: string | null; member_ids: string[] }) {
    const { data } = await apiClient.post<GroupDetails>("/groups", payload);
    return data;
  },
  async update(groupId: string, payload: { name: string; description: string | null; group_picture_url?: string | null }) {
    const { data } = await apiClient.put<GroupDetails>(`/groups/${groupId}`, payload);
    return data;
  },
  async addMembers(groupId: string, userIds: string[]) {
    const { data } = await apiClient.post<AddGroupMembersResponse>(`/groups/${groupId}/members`, {
      user_ids: userIds,
    });
    return data;
  },
  async removeMember(groupId: string, userId: string) {
    await apiClient.delete(`/groups/${groupId}/members/${userId}`);
  },
  async promoteAdmin(groupId: string, userId: string) {
    const { data } = await apiClient.post<GroupMember>(`/groups/${groupId}/admins/${userId}`);
    return data;
  },
  async demoteAdmin(groupId: string, userId: string) {
    await apiClient.delete(`/groups/${groupId}/admins/${userId}`);
  },
  async messageStats(groupId: string) {
    const { data } = await apiClient.get<GroupMessageStats>(`/groups/${groupId}/messages/stats`);
    return data;
  },
};
