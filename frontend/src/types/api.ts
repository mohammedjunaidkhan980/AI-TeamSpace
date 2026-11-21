export interface UserProfile {
  id: string;
  username: string;
  full_name: string;
  email: string;
  created_at: string;
  profile_picture_url?: string | null;
  bio?: string | null;
  status_message?: string | null;
}

export interface LoginResponse {
  access_token: string;
  token_type: "bearer";
  expires_in: number;
  user: Pick<UserProfile, "id" | "username" | "full_name" | "email" | "created_at">;
}

export interface RegisterRequest {
  username: string;
  full_name: string;
  email: string;
  password: string;
}

export interface GroupListItem {
  group_id: string;
  name: string;
  description: string | null;
  creator_id: string;
  created_at: string;
  member_count: number;
  current_user_role: "admin" | "member";
  last_message_at: string | null;
}

export interface GroupListResponse {
  items: GroupListItem[];
  limit: number;
  offset: number;
}

export interface GroupMember {
  user: PublicUserProfile;
  role: "admin" | "member";
  joined_at: string;
}

export interface GroupDetails {
  group_id: string;
  name: string;
  description: string | null;
  creator_id: string;
  group_picture_url: string | null;
  members: GroupMember[];
  member_count: number;
  created_at: string;
  updated_at: string;
  settings: Record<string, unknown>;
  ai_agents: Array<Record<string, unknown>>;
  last_message_at: string | null;
  nexconn_channel_id: string | null;
  nexconn_sync_status: "pending" | "synced" | "failed" | "disabled";
  nexconn_synced_at?: string | null;
}

export interface PublicUserProfile {
  id: string;
  username: string;
  full_name: string;
  profile_picture_url: string | null;
  bio: string | null;
  status_message: string | null;
  created_at: string;
}

export interface Page<T> {
  items: T[];
  limit: number;
  offset: number;
}

export interface ConnectionRequest {
  id: string;
  sender: PublicUserProfile;
  recipient: PublicUserProfile;
  status: "pending" | "accepted" | "rejected";
  created_at: string;
  updated_at: string;
}

export interface ConnectionActionResponse {
  id: string;
  status: "pending" | "accepted" | "rejected";
  message: string;
}

export interface AgentTemplate {
  template_id: string;
  name: string;
  description: string;
  role: string;
  capabilities: string[];
  system_prompt: string;
  model: string;
  temperature: number;
}

export interface GroupAgent {
  agent_id: string;
  group_id: string;
  template_id: string;
  name: string;
  description: string;
  system_prompt: string;
  model: string;
  temperature: number;
  capabilities: string[];
  enabled: boolean;
  created_by: string;
  created_at: string;
  updated_at: string;
  configuration: Record<string, unknown>;
}

export interface GroupAgentListResponse {
  items: GroupAgent[];
}

export interface AddGroupMembersResponse {
  members: GroupMember[];
  nexconn_sync_status: "pending" | "synced" | "failed" | "disabled";
}

export interface GroupMessageStats {
  total_message_count: number;
  human_message_count: number;
  ai_message_count: number;
  latest_message_at: string | null;
}

export type AIProcessingStatus = "not_required" | "pending" | "processing" | "completed" | "failed";
export type DeliveryStatus = "pending" | "sending" | "delivered" | "failed";

export interface MessageResponse {
  message_id: string;
  group_id: string;
  nexconn_message_id: string | null;
  sender: { id: string; type: "user" | "agent" | "system"; name: string };
  content: string;
  message_type: "text" | "file" | "image" | "system";
  attachments: Array<{ type: "file" | "image"; url: string; name?: string | null; mime_type?: string | null; size?: number | null }>;
  reply_to_message_id: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  is_deleted: boolean;
  agent_id: string | null;
  agent_name: string | null;
  orchestration_id: string | null;
  delivery_status: DeliveryStatus | null;
  ai_processing_status: AIProcessingStatus;
}

export interface MessageHistoryResponse {
  items: MessageResponse[];
  limit: number;
  next_cursor: string | null;
}

export interface OrchestrationAccepted {
  orchestration_id: string;
  message_id: string;
  status: "queued" | "processing" | "completed" | "failed";
}

export interface AIMessageDeliveryAccepted {
  orchestration_id: string;
  delivery_status: DeliveryStatus;
  message_id: string | null;
}

export interface AIMessageDeliveryStatus {
  orchestration_id: string;
  delivery_status: DeliveryStatus;
  message_id: string | null;
  sender_name: string | null;
  created_at: string | null;
  delivered_at: string | null;
  retry_count: number;
  error_message: string | null;
}

export interface AgentExecutionResult {
  agent_id: string;
  agent_name: string;
  task: string;
  response: string | null;
  status: "completed" | "failed";
  execution_time: number;
  error: string | null;
}

export interface OrchestrationRun {
  orchestration_id: string;
  message_id: string;
  group_id: string;
  status: "queued" | "processing" | "completed" | "failed";
  coordinator_plan: Record<string, unknown> | null;
  selected_agent_ids: string[];
  agent_results: AgentExecutionResult[];
  final_response: string | null;
  errors: string[];
  started_at: string;
  completed_at: string | null;
  execution_time: number | null;
  delivery_status: DeliveryStatus | null;
  citations: DocumentCitation[];
}

export type DocumentStatus = "uploaded" | "pending" | "processing" | "completed" | "failed";

export interface DocumentResponse {
  document_id: string;
  group_id: string;
  filename: string;
  file_type: string;
  file_size: number;
  uploader_id: string;
  uploader_name: string;
  created_at: string;
  updated_at: string;
  status: DocumentStatus;
  processing_error: string | null;
  metadata: Record<string, unknown>;
}

export interface DocumentListResponse {
  items: DocumentResponse[];
  limit: number;
  next_cursor: string | null;
}

export interface DocumentCitation {
  document_id: string;
  filename: string;
  chunk_index: number;
  page_number: number | null;
  excerpt: string;
}

export type NotificationType =
  | "connection_request"
  | "connection_accepted"
  | "group_invitation"
  | "group_membership"
  | "group_member_added"
  | "new_group_message"
  | "ai_response"
  | "document_processing_completed"
  | "document_processing_failed";

export interface NotificationItem {
  notification_id: string;
  type: NotificationType;
  title: string;
  description: string;
  related_entity_id: string | null;
  related_entity_type: string | null;
  group_id: string | null;
  is_read: boolean;
  created_at: string;
  metadata: Record<string, unknown>;
}

export interface NotificationListResponse {
  items: NotificationItem[];
  limit: number;
  next_cursor: string | null;
  unread_count: number;
}
