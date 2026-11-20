import { apiClient } from "./client";
import type { DocumentListResponse, DocumentResponse } from "../../types/api";

export const documentsApi = {
  async list(params: { groupId?: string; search?: string; before?: string; limit?: number } = {}) {
    const { data } = await apiClient.get<DocumentListResponse>("/documents", {
      params: {
        ...(params.groupId ? { group_id: params.groupId } : {}),
        ...(params.search ? { search: params.search } : {}),
        ...(params.before ? { before: params.before } : {}),
        limit: params.limit ?? 30,
      },
    });
    return data;
  },
  async groupList(groupId: string, before?: string) {
    const { data } = await apiClient.get<DocumentListResponse>(`/groups/${groupId}/documents`, {
      params: { limit: 30, ...(before ? { before } : {}) },
    });
    return data;
  },
  async upload(groupId: string, file: File, onProgress?: (progress: number) => void) {
    const formData = new FormData();
    formData.append("file", file);
    const { data } = await apiClient.post<DocumentResponse>(`/groups/${groupId}/documents`, formData, {
      headers: { "Content-Type": "multipart/form-data" },
      onUploadProgress: (event) => {
        if (event.total) onProgress?.(Math.round((event.loaded / event.total) * 100));
      },
    });
    return data;
  },
  async details(documentId: string) {
    const { data } = await apiClient.get<DocumentResponse>(`/documents/${documentId}`);
    return data;
  },
  async download(documentId: string) {
    const { data } = await apiClient.get<Blob>(`/documents/${documentId}/download`, {
      responseType: "blob",
    });
    return data;
  },
  async remove(documentId: string) {
    await apiClient.delete(`/documents/${documentId}`);
  },
  async retry(documentId: string) {
    const { data } = await apiClient.post<{ document_id: string; status: DocumentResponse["status"] }>(
      `/documents/${documentId}/retry`,
    );
    return data;
  },
};
