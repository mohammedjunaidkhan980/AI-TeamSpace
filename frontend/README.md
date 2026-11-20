# AI TeamSpace Frontend

React, Vite, TypeScript, Tailwind CSS, Radix UI primitives following the shadcn/ui composition pattern, React Router, TanStack Query, Axios, Zustand, and Lucide.

## Run locally

From `frontend`:

```powershell
npm install
Copy-Item .env.example .env
npm run dev
```

Set `VITE_API_BASE_URL` to the backend origin (default `http://localhost:8000`). No backend secrets belong in frontend environment variables. `npm run build` runs the TypeScript build and Vite production build.

## Implemented foundation

- Login, registration, session persistence for the browser tab, bearer-token requests, 401 handling, and local JWT-expiry handling.
- Protected and guest-only routes with a responsive, collapsible application shell.
- Dashboard with real group data and latest-message timestamps where available.
- Group listing, create modal (initial members are selected from accepted connections), group details, and admin-only editing.
- Teammate search, outgoing/incoming requests, accept/reject, and connection listing using backend APIs.
- Read-only agent-template catalog and profile settings.
- Global and group-scoped document listing, upload, download, processing status, retry, and authorized deletion.
- Persistent notification bell and paginated notification center with read/delete actions.

The group workspace includes overview, persisted chat history, members, AI agents, documents, and settings tabs. Member management uses the existing add/remove and promote/demote endpoints; leaving a group uses the existing self-removal endpoint. Agent management is group-specific, and uses the existing template/create/status/delete endpoints.

Backend API gaps are shown directly in the UI: group-member profiles omit email addresses (only the current user's own email is known), no group delete or ownership-transfer endpoint exists, and group visibility is not configurable. Group pictures accept an image URL only. The dashboard does not invent an activity feed; it uses only group timestamps supplied by the groups API.

## Messaging and AI orchestration

- The group Chat tab reads authenticated, cursor-paginated MongoDB-backed message history and refreshes it periodically. The official `@nexconn/chat` SDK session connects using a backend-issued token; SDK message events invalidate the history query, leaving MongoDB as the application history source of truth.
- Human text messages are sent through the authenticated backend endpoint with an idempotency key and delivered by the backend Nexconn integration. Failed messages can be retried. Attachments are not supported by this sending endpoint.
- Messages render human and AI identities, timestamps, delivery state, and available RAG source citations. Citation links open only documents accessible to the current group member.
- Users can soft-delete their own messages; group admins can also delete other members' messages. The backend enforces these permissions.
- "Ask AI agents" queues orchestration for an existing human text message. The UI displays the backend's orchestration status, agent results, and synthesized response. Failed AI-response delivery can be retried through the authenticated delivery endpoint.
- The Documents page lists documents from groups the user belongs to. Group document panels support upload and group-scoped listing. Only the uploader or a group admin can retry processing or delete a document; downloads and listings require group membership.
- Notification history is persisted by the backend and polled by the frontend. The notification bell routes connection requests, group activity, and document events to their relevant pages.
- Global search uses existing group-list and user-search APIs. It does not search messages or notifications.

## Nexconn configuration

Set `NEXCONN_ENABLED=true`, `NEXCONN_APP_KEY`, `NEXCONN_APP_SECRET`, and `NEXCONN_API_BASE_URL` in the backend `.env` using values provided for your Nexconn application. The frontend receives only the short-lived user token and App Key from authenticated backend endpoints; never put the App Secret in frontend environment variables. When Nexconn is disabled, message composition is unavailable and persisted history remains readable.

## Documents and retrieval

Backend uploads accept PDF, UTF-8 TXT, and DOCX files up to 20 MB, and store document files under `DOCUMENT_STORAGE_PATH` (default `./data/documents`). To index documents and provide citations, set `CHROMA_ENABLED=true`, configure `CHROMA_PERSIST_DIRECTORY`, and provide `GEMINI_API_KEY` or `GOOGLE_API_KEY`. Vector lookup filters by the group's ID. Upload and retry processing use in-process FastAPI background tasks; these jobs are not durable across a process crash. Use a durable queue before relying on this for production workloads.

## Build

```powershell
npm run build
```
