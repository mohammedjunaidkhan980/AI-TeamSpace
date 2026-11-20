# AI TeamSpace

AI TeamSpace is a collaborative workspace where people can work in groups, communicate through group chat, and ask specialized AI agents to help with group tasks. It combines a React web application with a FastAPI API, MongoDB persistence, optional Nexconn chat delivery, and optional Gemini-powered agent orchestration and document retrieval.

## Features

- Account registration, login, and authenticated user profiles.
- Groups, member roles, connections, and group-scoped permissions.
- Group chat backed by Nexconn, with messages persisted by the backend.
- Group AI-agent templates, enable/disable management, and LangGraph orchestration.
- Group document uploads, processing, ChromaDB retrieval, and source citations.
- Notifications and responsive dashboard/workspace pages.

AI orchestration and document embeddings require Google Gemini credentials. Nexconn chat requires credentials and an API origin assigned to your Nexconn application. These integrations are configured on the backend; secrets must never be placed in frontend environment variables.

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

## Technology

- **Frontend:** React, Vite, TypeScript, Tailwind CSS, React Router, TanStack Query, Axios, Zustand, and Lucide.
- **Backend:** Python 3.12+, FastAPI, Pydantic v2, PyMongo's async client, and Pytest.
- **Data and AI:** MongoDB, Google Gemini, LangGraph, and embedded ChromaDB.
- **Chat:** Nexconn server API and the Nexconn browser SDK.

## Local setup

### Prerequisites

- Python 3.12 or newer.
- Node.js and npm.
- MongoDB, running locally or available through a MongoDB connection string.
- Google Gemini API credentials for text generation and/or document embeddings.
- Nexconn application credentials and its assigned API origin to enable Nexconn chat. Nexconn is optional for local startup.

### Backend

In PowerShell:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `backend/.env` locally. Set `MONGODB_URL` and `MONGODB_DATABASE`, and replace the empty `JWT_SECRET_KEY` with a randomly generated secret (for example, generate one with `python -c "import secrets; print(secrets.token_urlsafe(48))"`). Never commit `.env`.

Start the API from the `backend` directory:

```powershell
uvicorn app.main:app --reload
```

- API: <http://localhost:8000>
- Swagger UI: <http://localhost:8000/docs>
- Health check: <http://localhost:8000/api/v1/health>

The health endpoint reports MongoDB connectivity. The backend can start without Nexconn; Gemini-dependent features need a configured Google API key.

### Frontend

In a second terminal:

```powershell
cd frontend
npm install
Copy-Item .env.example .env
npm run dev
```

The local application is served at <http://localhost:5173>. `VITE_API_BASE_URL` in `frontend/.env` should point to the backend origin (default `http://localhost:8000`). Only public frontend configuration belongs in `VITE_*` variables; do not put Gemini, Nexconn, JWT, or database secrets there.

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
