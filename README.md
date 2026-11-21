# AI TeamSpace

AI TeamSpace is a collaborative workspace where people can work in groups, communicate through group chat, and ask specialized AI agents to help with group tasks. It combines a React web application with a FastAPI API, MongoDB persistence, optional Nexconn chat delivery, and optional Gemini-powered agent orchestration and document retrieval.

## How to use AI TeamSpace

1. **Register and sign in.** Create an account with your name, username, email, and password, then sign in to open your workspace.
2. **Create or join a group.** When you create a group, you become its admin. You can add existing connections while creating it or later from group member settings. To join someone else's group, send a connection request to its admin; after the connection is accepted, ask the admin to add you. There is no direct group join-request button yet.
3. **Chat with the group.** Members can exchange real-time messages in the group chat. Message history is persisted by the backend, so it remains available when you return. Admins can add multiple accepted connections; member additions are submitted in batches of up to 100.
4. **Share documents.** Any group member can upload a PDF, TXT, or DOCX file. TeamSpace processes it in the background. Once indexing completes, relevant excerpts can be retrieved to help answer group questions; the configured upload-size limit applies.
5. **Use AI teammates.** Group admins choose which agents are enabled. In group chat, type `@` and select an agent, such as Research, to direct a request. The coordinator can also assign broader requests to relevant enabled agents. When matching document excerpts are available, they may be included as context and sources.

AI responses and document embeddings require Google Gemini credentials. Real-time chat requires Nexconn to be enabled and configured on the backend. These integrations are optional for starting the app; keep all service secrets out of frontend variables.

## Technology used

- **Frontend:** React, Vite, TypeScript, Tailwind CSS, React Router, TanStack Query, Axios, Zustand, and Lucide.
- **Backend:** Python 3.12+, FastAPI, Pydantic v2, PyMongo's asynchronous client, and Pytest.
- **Application data and files:** MongoDB; uploaded files use local storage or MongoDB GridFS, depending on configuration.
- **AI and retrieval:** Google Gemini for language generation and embeddings, LangGraph for agent orchestration, and ChromaDB or MongoDB vector search depending on deployment configuration.
- **Chat:** Nexconn browser SDK for authenticated sessions and message events, plus a backend Nexconn integration for group channels and message delivery.

## Run locally

### Prerequisites

- Python 3.12 or newer.
- Node.js and npm.
- MongoDB, running locally or available through a MongoDB connection string.
- Gemini credentials for AI responses and document embeddings. Optional for app startup.
- Nexconn App Key, App Secret, and assigned API origin for real-time chat. Optional for app startup.

### 1. Set up the backend

From the repository root, in PowerShell:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `backend/.env` and set `MONGODB_URL` and `MONGODB_DATABASE`. Replace `JWT_SECRET_KEY` with a strong random secret. Add `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) for AI features. To enable Nexconn, set `NEXCONN_ENABLED=true` and provide the Nexconn values assigned to your application. Never commit `.env` or put backend secrets in frontend variables.

Start the API from the `backend` directory:

```powershell
uvicorn app.main:app --reload
```

The API is at <http://localhost:8000>, Swagger UI at <http://localhost:8000/docs>, and the health check at <http://localhost:8000/api/v1/health>.

### 2. Set up the frontend

In a second terminal, from the repository root:

```powershell
cd frontend
npm install
Copy-Item .env.example .env
npm run dev
```

Open <http://localhost:5173>. Set `VITE_API_BASE_URL` in `frontend/.env` to the backend origin (default `http://localhost:8000`). Only public configuration belongs in `VITE_*` variables; never put Gemini, Nexconn, JWT, or database secrets there.

## Project structure

```text
AI-TeamSpace/
├── backend/
│   ├── app/
│   │   ├── api/              # Versioned REST endpoints
│   │   ├── core/             # Settings, security, and shared exceptions
│   │   ├── database/         # MongoDB and indexes
│   │   ├── repositories/     # Database access
│   │   ├── services/         # Auth, documents, Nexconn, and orchestration
│   │   └── schemas/          # Pydantic request/response models
│   ├── tests/
│   ├── .env.example
│   └── requirements.txt
└── frontend/
    ├── src/
    │   ├── app/              # Router and providers
    │   ├── components/       # Shared and layout components
    │   ├── features/         # Auth, groups, chat, agents, documents, etc.
    │   ├── services/         # API client and endpoint services
    │   └── stores/           # Client state
    ├── .env.example
    └── package.json
```

## Integration configuration

All backend secrets and service credentials belong in the untracked `backend/.env`. The committed `backend/.env.example` contains placeholders and safe local defaults; copy it to `.env` and supply values locally.

### MongoDB

Configure `MONGODB_URL` and `MONGODB_DATABASE`. Use a local MongoDB instance for development or a connection string supplied by your database provider. Do not commit credentials embedded in connection strings.

### Gemini and AI agents

Set `GEMINI_API_KEY` or `GOOGLE_API_KEY` in the backend environment. `GEMINI_MODEL` controls text generation; `GEMINI_EMBEDDING_MODEL` controls document embeddings. Built-in agent templates use the configured text model, and group admins can manage which template agents are enabled in their groups.

### Nexconn

Nexconn is disabled by default. To enable it, obtain the App Key, App Secret, and API base URL assigned to your Nexconn application, then set `NEXCONN_ENABLED=true` and those values in `backend/.env`. The backend uses the App Secret for server-side requests. Never add it to the frontend environment, source code, logs, or this repository. Do not guess an API origin; use the one supplied for your application.

### Document storage and retrieval

For local development, set `USE_MONGO_STORAGE=false` to keep uploaded files under `DOCUMENT_STORAGE_PATH` and use embedded ChromaDB configured by `CHROMA_ENABLED`, `CHROMA_PERSIST_DIRECTORY`, and `CHROMA_COLLECTION_NAME`.

For deployments without a persistent filesystem, set `USE_MONGO_STORAGE=true`. Files are stored in MongoDB GridFS and embeddings/chunks in MongoDB's `document_chunks` collection; Gemini remains the embedding provider. The example caps MongoDB-backed uploads at 5 MiB (`MONGO_DOCUMENT_MAX_UPLOAD_BYTES`) and limits each in-memory group search to `MONGO_VECTOR_MAX_CANDIDATES` chunks. Retrieval applies the group filter in MongoDB before cosine ranking.

Atlas M0 has a 512 MB total storage limit. GridFS files, chunks, embeddings, indexes, and the rest of the application all use that same quota; the per-file cap does not guarantee available quota. Monitor Atlas storage and delete/archive documents before the free-tier limit is reached. MongoDB storage errors are returned as service-unavailable or insufficient-storage responses. Switching this flag does not migrate or delete existing local documents; records and files already stored locally remain in local storage and are not visible through MongoDB mode.

## Tests and checks

Run backend tests from `backend`:

```powershell
python -m pytest
```

Build and type-check the frontend from `frontend`:

```powershell
npm run build
```

## Repository safety

Do not commit `.env` files, API keys, JWT secrets, database credentials, private keys, local MongoDB/SQLite data, ChromaDB persistence, uploads, or user-generated data. Root and nested `.gitignore` files exclude these local files while allowing `.env.example` templates. Before publishing, inspect the staged file list and scan the staged content for credentials.
