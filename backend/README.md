# AI TeamSpace Backend

The backend uses FastAPI, Pydantic Settings, and PyMongo's asynchronous MongoDB client. It includes user registration, JWT login, protected profiles, connections, group management, and an optional Nexconn real-time chat integration. MongoDB remains the source of truth for users, group membership, and permissions.

## Requirements

- Python 3.12 or newer
- MongoDB (local or hosted)

## Setup (Windows PowerShell)

From the `backend` directory:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Set `MONGODB_URL` in `.env` to your MongoDB connection string and set `JWT_SECRET_KEY` to a cryptographically random secret of at least 32 bytes. Nexconn is disabled by default; the application starts without Nexconn credentials. Do not commit `.env`.

## Run

Start the API from the `backend` directory:

```powershell
uvicorn app.main:app --reload
```

- Health: <http://localhost:8000/api/v1/health>
- Register: `POST /api/v1/auth/register`
- Log in: `POST /api/v1/auth/login`
- Current user: `GET /api/v1/auth/me` (Bearer token required)
- Log out: `POST /api/v1/auth/logout` (Bearer token required; revokes the token)
- Get profile: `GET /api/v1/users/me` (Bearer token required)
- Update profile: `PUT /api/v1/users/me` (Bearer token required)
- Search users: `GET /api/v1/users/search?q=alice` (Bearer token required)
- Public profile: `GET /api/v1/users/{user_id}` (Bearer token required)
- Send friend request: `POST /api/v1/connections/requests`
- Incoming/outgoing requests: `GET /api/v1/connections/requests/incoming` and `/api/v1/connections/requests/outgoing`
- Accept/reject request: `POST /api/v1/connections/requests/{request_id}/accept` or `/reject`
- Cancel request: `DELETE /api/v1/connections/requests/{request_id}`
- List/remove connections: `GET /api/v1/connections` and `DELETE /api/v1/connections/{user_id}`
- Create/list groups: `POST /api/v1/groups` and `GET /api/v1/groups`
- Group details/update: `GET /api/v1/groups/{group_id}` and `PUT /api/v1/groups/{group_id}`
- Add/remove members: `POST /api/v1/groups/{group_id}/members` and `DELETE /api/v1/groups/{group_id}/members/{user_id}`
- Promote/demote admins: `POST /api/v1/groups/{group_id}/admins/{user_id}` and `DELETE /api/v1/groups/{group_id}/admins/{user_id}`
- Nexconn access token/status: `POST /api/v1/nexconn/token` and `GET /api/v1/nexconn/status`
- Group chat channel: `GET /api/v1/groups/{group_id}/chat-channel` (group members only)
- Group history/stats: `GET /api/v1/groups/{group_id}/messages` and `/messages/stats`
- Send/retry human text messages: `POST /api/v1/groups/{group_id}/messages` and `POST /api/v1/messages/{message_id}/retry`
- Message retrieval/deletion: `GET /api/v1/messages/{message_id}` and `DELETE /api/v1/messages/{message_id}`
- Nexconn message event receiver: `POST /api/v1/webhooks/nexconn/messages`
- Agent templates: `GET /api/v1/agents/templates`
- Group agents: `POST` and `GET /api/v1/groups/{group_id}/agents`
- Group agent details/update/status/removal: `GET`, `PUT`, `PATCH .../{agent_id}/status`, and `DELETE /api/v1/groups/{group_id}/agents/{agent_id}`
- Queue message orchestration: `POST /api/v1/groups/{group_id}/messages/{message_id}/ai-process`
- Orchestration status/results: `GET /api/v1/groups/{group_id}/orchestrations/{orchestration_id}`
- Queue/retry AI response delivery: `POST /api/v1/groups/{group_id}/orchestrations/{orchestration_id}/deliver`
- AI response delivery status: `GET /api/v1/groups/{group_id}/orchestrations/{orchestration_id}/delivery-status`
- Group documents: `POST` and `GET /api/v1/groups/{group_id}/documents`
- User documents: `GET /api/v1/documents`, `GET /api/v1/documents/{document_id}`, and `GET /api/v1/documents/{document_id}/download`
- Retry/delete documents: `POST /api/v1/documents/{document_id}/retry` and `DELETE /api/v1/documents/{document_id}`
- Notifications: `GET /api/v1/notifications`, `GET /api/v1/notifications/unread-count`, `PUT /api/v1/notifications/{notification_id}/read`, `PUT /api/v1/notifications/read-all`, and `DELETE /api/v1/notifications/{notification_id}`
- Swagger UI: <http://localhost:8000/docs>
- ReDoc: <http://localhost:8000/redoc>

The health endpoint returns `200` with `{"status":"ok","mongodb":"connected"}` when MongoDB responds to a ping. It returns `503` with a `degraded` application status when MongoDB is unavailable. The API can start without an available MongoDB server; database connectivity is checked by the health endpoint.

## Tests

Run from the `backend` directory:

```powershell
pytest
```

## Nexconn Chat Setup

The integration uses Nexconn's server-side API and the official Nexconn request signature. To enable it:

1. Create or select your Nexconn application in the [Nexconn Console](https://console.nexconn.ai/agile/im/service/config). If your account does not expose application credentials, request an app key, secret, and API domain from your Nexconn account contact.
2. Obtain the application's App Key, App Secret, and the API base URL assigned to that application. The API base URL is deployment-specific; use the value Nexconn provides rather than guessing a public host.
3. Set these values in `backend/.env`:

   ```dotenv
   NEXCONN_ENABLED=true
   NEXCONN_APP_KEY=your-app-key
   NEXCONN_APP_SECRET=your-app-secret
   NEXCONN_API_BASE_URL=https://the-api-host-provided-by-nexconn
   ```

   HTTPS is required except for localhost development. The App Secret is used only by the backend and is never returned by an API.

The backend signs server requests with the configured App Key and Secret. `POST /api/v1/nexconn/token` requires the user's TeamSpace JWT, synchronizes that authenticated user's ID and profile, then returns a Nexconn access token, the same internal user ID, and the App Key. The Nexconn API documentation does not specify a token expiry value, so the backend does not claim one.

Users are registered in Nexconn using their internal MongoDB user ID and full name. Later token generation refreshes their supported profile fields. When a group is created, the backend creates one Nexconn group channel using the MongoDB group ID as its channel ID, then synchronizes its members. Member additions and removals are reconciled with the channel. The group document records the channel mapping and synchronization status; an external API failure does not roll back MongoDB's source-of-truth change, and the failure status remains visible in group responses. Access to the channel ID is restricted to current group members.

### Message persistence and webhooks

Nexconn remains responsible for live message transport. To mirror successfully delivered messages to MongoDB, configure the webhook URL in the Nexconn Console under **Chat > Chat settings > Webhooks**, and subscribe to the documented `message:send` event. Set the URL to `https://<your-api-host>/api/v1/webhooks/nexconn/messages`. The endpoint accepts group-channel (`channelType: 3`) events, verifies Nexconn's documented `AppKey`, `Nonce`, `Timestamp`, and `Signature` headers, verifies the Nexconn sender ID is a current member, and deduplicates by Nexconn message ID.

History is returned chronologically in pages of 50 by default (maximum 100). Use the response `next_cursor` as the `before` query parameter to fetch older messages. Deleted messages are soft-deleted and excluded from history. Only the sender or a group admin can delete. Message processing events are stored as durable pending records when a group has enabled agents. The asynchronous orchestration service processes those events; messages are never taken from a custom WebSocket server.

The receiver applies the documented signature formula `SHA1(App Secret + Nonce + Timestamp)` and rejects timestamps more than five minutes from server time. Nexconn's documented `message:send` content is a message-type-dependent opaque string. Text messages (`RC:TxtMsg`) are normalized to their text content; other types retain the original content, with an empty normalized attachment list until Nexconn's per-type attachment payload contract is integrated. Configure the Nexconn webhook delivery URL as HTTPS in production; Nexconn may also require its documented regional webhook IPs to be allowed through your firewall.

| Environment variable | Purpose |
| --- | --- |
| `NEXCONN_ENABLED` | Enables the integration; defaults to `false`. |
| `NEXCONN_APP_KEY` | Nexconn application identifier used in signed server requests and token responses. |
| `NEXCONN_APP_SECRET` | Backend-only signing secret; never returned by the API. |
| `NEXCONN_API_BASE_URL` | HTTPS API origin supplied for the Nexconn application. |

Nexconn client and integration calls are mocked in the automated test suite; no live Nexconn credentials are required to run tests:

```powershell
pytest
```

## Group AI Agent Management

The backend exposes reusable templates at `GET /api/v1/agents/templates`: Research, Coding, Data Analyst, Writing, Project Manager, and Coordinator. Templates are static and are not stored as group agents.

Group admins can create an agent with `POST /api/v1/groups/{group_id}/agents`, using a `template_id` and optional custom `name`, `custom_system_prompt`, `model`, `temperature`, `capabilities`, or `configuration`. Model names are limited to letters, digits, dots, underscores, and hyphens; temperature must be between 0 and 1. Configuration accepts only `max_tokens`, `top_p`, and `response_format`; provider credentials and arbitrary endpoint settings are not accepted. The same template can be used in different groups, while each group can have only one active instance of a given template.

Group members can list and view their group's agents. Only admins can create, update, enable/disable, or remove agents. Removed agents are soft-deleted, and disabled or removed agents are excluded from the group's active-agent summary. Historical messages are not changed. Configuration and template endpoints do not execute LLMs; see the orchestration section for message-triggered execution.

Example create request:

```json
{
  "template_id": "research",
  "name": "Market Research",
  "temperature": 0.4,
  "configuration": {
    "max_tokens": 2048,
    "top_p": 0.9,
    "response_format": "text"
  }
}
```

In Swagger (`/docs`), authorize with a TeamSpace bearer token. Use an admin token for create/update/status/delete operations and a member token for listing and details.

## LangGraph Multi-Agent Orchestration

The orchestration engine uses one reusable LangGraph workflow:

`Coordinator -> conditional route -> parallel/sequential agent execution -> synthesis -> persistence`

The coordinator returns a Pydantic-validated plan and can select only enabled agents loaded from the current group. The coordinator's selection is intersected with those available group agents; unknown or foreign IDs are discarded. Agents receive their own configured system prompt, the original message, a bounded recent history, and only dependency results assigned by the coordinator. User messages and peer-agent output are passed as untrusted content, no tools or external sources are exposed, and each provider request receives a system-level instruction against prompt injection.

Independent tasks run concurrently up to `MAX_PARALLEL_AGENTS`. A coordinator may request sequential execution and specify dependencies; dependent agents receive only the successful outputs of their listed predecessors. Individual failures are captured per agent. A failed coordinator uses a constrained fallback over available agents; if no agent succeeds, the orchestration returns a non-fabricated failure response. A single successful agent response is used directly; multiple successful responses are synthesized.

Set either `GOOGLE_API_KEY` (preferred) or the existing `GEMINI_API_KEY` in `backend/.env`. No key is required to start the API or run the mocked tests. Additional settings:

| Environment variable | Purpose | Default |
| --- | --- | --- |
| `GEMINI_MODEL` | Gemini model used for coordination, synthesis, and built-in agent templates; explicitly customized agents can override it. | `gemini-3.8-flash` |
| `DEFAULT_LLM_TEMPERATURE` | Temperature for coordination and synthesis. | `0.2` |
| `ORCHESTRATION_TIMEOUT_SECONDS` | Per-provider and whole-workflow timeout. | `120` |
| `MAX_PARALLEL_AGENTS` | Maximum in-flight agent calls; also caps agents used by the coordinator fallback. | `4` |
| `ORCHESTRATION_HISTORY_LIMIT` | Number of recent group messages included as context. | `20` |

Eligible webhook-ingested human messages are queued for orchestration when the group has enabled agents. To manually queue an active human message, call `POST /api/v1/groups/{group_id}/messages/{message_id}/ai-process`; this returns `202` with an orchestration ID without waiting for model work. Any group member can queue and retrieve runs for their group. Duplicate runs for one message are rejected. `GET /api/v1/groups/{group_id}/orchestrations/{orchestration_id}` returns the plan, per-agent outcomes, and final response when available.

Completed runs and results are stored in `orchestration_runs`. A successful final answer is persisted as an AI group message before the delivery attempt, linked to the source message. Orchestration completion and Nexconn delivery have separate statuses, so a failed delivery does not erase the response or change a completed run to failed. API keys are read from settings only and are not written to MongoDB or orchestration responses.

### AI response delivery

When Nexconn is enabled, completed orchestration results are sent through the documented Nexconn server-side group-message API (`POST /v4/group-channel/message/send`). Each AI sender has a deterministic, group-scoped Nexconn identity (`ai` + group ID + agent ID); AI responses therefore do not use a human participant's Nexconn identity. The backend registers/refreshes this identity through Nexconn's documented access-token issuance API before sending. The default `AI_RESPONSE_DELIVERY_MODE=coordinator_only` sends only the final synthesized response. Set it to `agents_and_coordinator` to deliver successful individual agent responses before the Coordinator result.

The orchestration-linked message is written to MongoDB with a stable delivery key before the network call. Delivery status is `pending`, `sending`, `delivered`, or `failed`, independent of orchestration status. The delivery endpoint requires group membership and a completed run; a subsequent call can retry failed delivery. Members can inspect status through the delivery-status endpoint. Retry count and exponential backoff are configurable; permanent API errors are not retried. Message history includes AI messages and their sender identity.

Nexconn's documented send response provides a remote message ID, which is stored to deduplicate the corresponding webhook event. Nexconn's server API does not document an idempotency key for sends. As a result, if Nexconn accepts a message but the backend times out before receiving the receipt or webhook, an automatic retry may deliver a duplicate. The persisted local delivery key prevents duplicate local records, but cannot provide exactly-once remote delivery in that ambiguous timeout case.

| Environment variable | Purpose | Default |
| --- | --- | --- |
| `AI_RESPONSE_DELIVERY_MODE` | `coordinator_only` or `agents_and_coordinator`. | `coordinator_only` |
| `NEXCONN_DELIVERY_MAX_RETRIES` | Additional retries for transient delivery failures. | `3` |
| `NEXCONN_DELIVERY_RETRY_BASE_SECONDS` | Base delay for exponential backoff. | `0.5` |

Manual delivery example:

```http
POST /api/v1/groups/65a000000000000000000001/orchestrations/4abc.../deliver
Authorization: Bearer <TeamSpace JWT>
```

The response is `202 Accepted` with the orchestration ID, delivery status, and persisted message ID. Retrieve the latest status with:

```http
GET /api/v1/groups/65a000000000000000000001/orchestrations/4abc.../delivery-status
Authorization: Bearer <TeamSpace JWT>
```

Example trigger:

```http
POST /api/v1/groups/65a000000000000000000001/messages/65a000000000000000000002/ai-process
Authorization: Bearer <TeamSpace JWT>
```

Tests use a mocked provider and do not call Gemini:

```powershell
pytest
```

Official references:

- [Nexconn Realtime Chat guide](https://docs.nexconn.ai/guides/realtime-chat/intro-chat)
- [Nexconn Platform Chat API](https://docs.nexconn.ai/platform-chat-api)
- [Nexconn webhook overview and signature verification](https://docs.nexconn.ai/platform-chat-api/webhook/overview)
- [Nexconn message:send payload](https://docs.nexconn.ai/platform-chat-api/webhook/message/send)
- [Official Nexconn Python server SDK](https://github.com/NexconnAI-Dev/nexconn-server-sdk-python)

## Human message sending and live delivery

Authenticated group members can send text with `POST /api/v1/groups/{group_id}/messages`. Requests require an `Idempotency-Key` header (16–128 characters); the backend persists the message before sending through Nexconn's documented server-side group-message API. Failed messages can be retried with `POST /api/v1/messages/{message_id}/retry`. Only text messages are currently supported by this sending endpoint; attachments are rejected rather than sent with an undocumented payload. Nexconn's server API does not guarantee idempotent remote sends, so an accepted request whose response times out may still be duplicated on retry.

The frontend connects to Nexconn through the official `@nexconn/chat` SDK. It obtains credentials from the authenticated backend, listens for supported message updates, and refreshes the MongoDB-backed message history. Nexconn SDK events are not used as a replacement for persisted application history.

## Documents and group-scoped retrieval

Upload a PDF, UTF-8 TXT, or DOCX file to a group with `POST /api/v1/groups/{group_id}/documents` (multipart field `file`). The per-file default limit is 20 MiB. All document list, detail, download, retry, and delete operations require group membership. Only the uploader or a group admin can retry processing or delete the file. The backend stores files locally under `DOCUMENT_STORAGE_PATH` (default `./data/documents`).

To index content, set `CHROMA_ENABLED=true`, configure `CHROMA_PERSIST_DIRECTORY` (default `./data/chroma`), and supply `GEMINI_API_KEY` or `GOOGLE_API_KEY`. At startup, the backend creates the persistent directory and configured collection. Text is extracted, chunked, embedded with `GEMINI_EMBEDDING_MODEL`, and stored with group/document metadata. Retrieval applies a Chroma `group_id` filter and checks returned metadata before supplying excerpts to the orchestration. AI message metadata and orchestration responses include source citations when retrieval returns matching excerpts. Gemini model availability depends on the API key's access; the configured text model must be enabled for that key.

Gemini 3.6 and later APIs deprecate `temperature`, `top_p`, and `top_k`. The provider omits sampling parameters for those models; older model families continue to use supported agent settings.

Document upload and retry currently schedule processing with FastAPI in-process background tasks. These jobs are not durable across process crashes; use a durable queue before relying on processing in production. Chroma is disabled by default, so document processing will not complete until it is enabled and embedding credentials and dependencies are available. Relevant settings:

| Environment variable | Purpose | Default |
| --- | --- | --- |
| `DOCUMENT_STORAGE_PATH` | Local document storage directory. | `./data/documents` |
| `DOCUMENT_MAX_UPLOAD_BYTES` | Maximum bytes per upload. | `20971520` |
| `DOCUMENT_MAX_TEXT_CHARACTERS` | Maximum extracted text size. | `2000000` |
| `DOCUMENT_CHUNK_SIZE` / `DOCUMENT_CHUNK_OVERLAP` | Chunking parameters. | `1200` / `150` |
| `CHROMA_ENABLED` | Enables vector indexing and retrieval. | `false` |
| `CHROMA_PERSIST_DIRECTORY` | Persistent Chroma database directory. | `./data/chroma` |
| `CHROMA_COLLECTION_NAME` | Collection used for document vectors. | `ai_teamspace_documents` |
| `GEMINI_EMBEDDING_MODEL` | Gemini embeddings model identifier. | `gemini-embedding-001` |

## Persistent notifications

Notifications are stored per recipient in MongoDB with a unique event key to avoid duplicate event records. Authenticated users can list and paginate their own notifications, retrieve unread counts, mark one or all as read, and delete their own notification. Connection, group membership/invitation, group message, AI response, and document processing events create notifications where applicable. The frontend polls the notification API; notifications are not delivered over Nexconn.

## Structure

- `app/core/`: configuration, logging, JWT/password security, and exception handling
- `app/database/`: reusable MongoDB client, database dependency, and index registration
- `app/api/v1/`: versioned REST router, health, authentication, users, connections, groups, and Nexconn endpoints
- `app/schemas/`: Pydantic request/response schemas
- `app/repositories/`: user persistence
- `app/repositories/connections.py`: friend-request and accepted-connection persistence
- `app/repositories/groups.py`: group persistence, memberships, and role changes
- `app/repositories/messages.py`: group message history, persistence, statistics, and soft deletion
- `app/services/message_processing.py`: asynchronous processing queue and processor interface
- `app/services/orchestration/`: reusable LangGraph workflow, Gemini provider, coordinator, worker execution, and synthesis
- `app/services/messaging/ai_message_delivery.py`: idempotent local AI message persistence, sender identity, Nexconn delivery, and retry state
- `app/repositories/orchestrations.py`: durable run persistence
- `app/models/`, `services/`, `agents/`, `middleware/`, `utils/`: extension points for future features
- `tests/`: API tests
