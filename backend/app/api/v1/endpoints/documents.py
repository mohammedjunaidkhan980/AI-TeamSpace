import io
import logging
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any

from bson import ObjectId
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from pymongo.database import Database

from app.core.config import Settings
from app.core.security import get_current_user
from app.database.mongodb import get_database
from app.repositories.documents import (
    get_document,
    insert_document,
    list_documents,
    list_group_documents,
    set_document_status,
)
from app.repositories.groups import get_group, get_member_role
from app.repositories.users import get_user_by_id
from app.schemas.auth import AuthenticatedUser
from app.schemas.documents import (
    DocumentListResponse,
    DocumentResponse,
    DocumentRetryResponse,
)
from app.services.document_processing import DocumentProcessingService
from app.services.document_storage import LocalDocumentStorage

logger = logging.getLogger(__name__)
documents_router = APIRouter()
group_documents_router = APIRouter()
ALLOWED_FORMATS = {
    ".pdf": {"application/pdf", "application/octet-stream"},
    ".txt": {"text/plain", "application/octet-stream"},
    ".docx": {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/octet-stream",
    },
}


async def _require_group(
    database: Database[dict[str, Any]], group_id: str, user_id: str
) -> tuple[dict[str, Any], str]:
    if not ObjectId.is_valid(group_id):
        raise HTTPException(status_code=404, detail="Group not found")
    group = await get_group(database, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    role = get_member_role(group, user_id)
    if role is None:
        raise HTTPException(status_code=403, detail="Group membership required")
    return group, role


def _document_response(document: dict[str, Any]) -> DocumentResponse:
    return DocumentResponse(
        document_id=str(document["_id"]),
        group_id=str(document["group_id"]),
        filename=document["filename"],
        file_type=document["file_type"],
        file_size=document["file_size"],
        uploader_id=str(document["uploader_id"]),
        uploader_name=document["uploader_name"],
        created_at=document["created_at"],
        updated_at=document["updated_at"],
        status=document["status"],
        processing_error=document.get("processing_error"),
        metadata=document.get("metadata", {}),
    )


async def _validate_upload(
    upload: UploadFile, settings: Settings
) -> tuple[str, bytes]:
    filename = upload.filename or ""
    if (
        not filename
        or len(filename) > 255
        or filename != Path(filename).name
        or "/" in filename
        or "\\" in filename
        or any(ord(char) < 32 or ord(char) == 127 for char in filename)
    ):
        raise HTTPException(status_code=422, detail="Invalid filename")
    extension = Path(filename).suffix.lower()
    allowed_mimes = ALLOWED_FORMATS.get(extension)
    if allowed_mimes is None:
        raise HTTPException(status_code=415, detail="Only PDF, TXT, and DOCX files are supported")
    if upload.content_type not in allowed_mimes:
        raise HTTPException(status_code=415, detail="File content type does not match a supported format")
    data = bytearray()
    while chunk := await upload.read(1024 * 1024):
        data.extend(chunk)
        if len(data) > settings.document_max_upload_bytes:
            raise HTTPException(status_code=413, detail="Document exceeds the upload size limit")
    content = bytes(data)
    if not content:
        raise HTTPException(status_code=422, detail="Document is empty")
    if extension == ".pdf" and not content.startswith(b"%PDF-"):
        raise HTTPException(status_code=422, detail="File content is not a valid PDF")
    if extension == ".docx":
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                entries = archive.infolist()
        except zipfile.BadZipFile:
            raise HTTPException(
                status_code=422, detail="File content is not a valid DOCX archive"
            ) from None
        required_entries = {"[Content_Types].xml", "word/document.xml"}
        if not required_entries.issubset({entry.filename for entry in entries}):
            raise HTTPException(
                status_code=422, detail="File content is not a valid DOCX document"
            )
        maximum_archive_size = settings.document_max_text_characters * 16
        if sum(entry.file_size for entry in entries) > maximum_archive_size:
            raise HTTPException(
                status_code=413,
                detail="Document archive expands beyond the processing limit",
            )
    if extension == ".txt":
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise HTTPException(status_code=422, detail="Text documents must use UTF-8 encoding") from None
        if "\x00" in text:
            raise HTTPException(status_code=422, detail="Text document contains binary data")
    return extension, content


def _processing_service(
    database: Database[dict[str, Any]], settings: Settings
) -> DocumentProcessingService:
    return DocumentProcessingService(database, settings)


@group_documents_router.post(
    "/{group_id}/documents",
    response_model=DocumentResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload a document to a group",
)
async def upload_group_document(
    group_id: str,
    background_tasks: BackgroundTasks,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    database: Annotated[Database[dict[str, Any]], Depends(get_database)],
    request: Request,
    file: Annotated[UploadFile, File()],
) -> DocumentResponse:
    settings: Settings = request.app.state.settings
    group, _ = await _require_group(database, group_id, current_user.id)
    extension, data = await _validate_upload(file, settings)
    user = await get_user_by_id(database, current_user.id)
    if user is None:
        raise HTTPException(status_code=401, detail="Authenticated user not found")
    filename = file.filename or f"document{extension}"
    storage_key = f"{uuid.uuid4().hex}{extension}"
    storage = LocalDocumentStorage(settings)
    await storage.put(storage_key, data)
    now = datetime.now(timezone.utc)
    try:
        document = await insert_document(
            database,
            {
                "group_id": group["_id"],
                "filename": filename,
                "file_type": extension.lstrip("."),
                "mime_type": file.content_type,
                "file_size": len(data),
                "uploader_id": ObjectId(current_user.id),
                "uploader_name": user["full_name"],
                "storage_key": storage_key,
                "created_at": now,
                "updated_at": now,
                "status": "pending",
                "processing_error": None,
                "metadata": {},
            },
        )
    except Exception:
        await storage.delete(storage_key)
        raise
    background_tasks.add_task(
        _processing_service(database, settings).process,
        str(document["_id"]),
    )
    return _document_response(document)


@documents_router.get("", response_model=DocumentListResponse)
async def get_documents(
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    database: Annotated[Database[dict[str, Any]], Depends(get_database)],
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    before: Annotated[str | None, Query()] = None,
    group_id: Annotated[str | None, Query()] = None,
    search: Annotated[str | None, Query(max_length=100)] = None,
) -> DocumentListResponse:
    memberships = await database["groups"].find(
        {"members.user_id": ObjectId(current_user.id)},
        projection={"_id": 1},
    ).to_list(length=1000)
    group_ids = [group["_id"] for group in memberships]
    selected_group = None
    if group_id is not None:
        group, _ = await _require_group(database, group_id, current_user.id)
        selected_group = group["_id"]
    documents, cursor = await list_documents(
        database,
        group_ids=group_ids,
        limit=limit,
        before=before,
        group_id=selected_group,
        search=search,
    )
    return DocumentListResponse(
        items=[_document_response(item) for item in documents],
        limit=limit,
        next_cursor=cursor,
    )


@group_documents_router.get("/{group_id}/documents", response_model=DocumentListResponse)
async def get_group_documents(
    group_id: str,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    database: Annotated[Database[dict[str, Any]], Depends(get_database)],
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    before: Annotated[str | None, Query()] = None,
    search: Annotated[str | None, Query(max_length=100)] = None,
) -> DocumentListResponse:
    group, _ = await _require_group(database, group_id, current_user.id)
    documents, cursor = await list_group_documents(
        database,
        group_id=group["_id"],
        limit=limit,
        before=before,
        search=search,
    )
    return DocumentListResponse(
        items=[_document_response(item) for item in documents],
        limit=limit,
        next_cursor=cursor,
    )


@documents_router.get("/{document_id}", response_model=DocumentResponse)
async def get_document_details(
    document_id: str,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    database: Annotated[Database[dict[str, Any]], Depends(get_database)],
) -> DocumentResponse:
    document = await get_document(database, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    await _require_group(database, str(document["group_id"]), current_user.id)
    return _document_response(document)


@documents_router.get("/{document_id}/download")
async def download_document(
    document_id: str,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    database: Annotated[Database[dict[str, Any]], Depends(get_database)],
    request: Request,
) -> FileResponse:
    document = await get_document(database, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    await _require_group(database, str(document["group_id"]), current_user.id)
    path = LocalDocumentStorage(request.app.state.settings).path_for(
        document["storage_key"]
    )
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Document file is unavailable")
    return FileResponse(
        path=path,
        media_type=document.get("mime_type", "application/octet-stream"),
        filename=document["filename"],
    )


@documents_router.post("/{document_id}/retry", response_model=DocumentRetryResponse)
async def retry_document_processing(
    document_id: str,
    background_tasks: BackgroundTasks,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    database: Annotated[Database[dict[str, Any]], Depends(get_database)],
    request: Request,
) -> DocumentRetryResponse:
    document = await get_document(database, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    group, role = await _require_group(database, str(document["group_id"]), current_user.id)
    if str(document["uploader_id"]) != current_user.id and role != "admin":
        raise HTTPException(status_code=403, detail="Only the uploader or a group admin can retry processing")
    if document["status"] != "failed":
        raise HTTPException(status_code=409, detail="Only failed document processing can be retried")
    await set_document_status(
        database, document_id=document["_id"], status="pending"
    )
    background_tasks.add_task(
        _processing_service(database, request.app.state.settings).process,
        document_id,
    )
    return DocumentRetryResponse(document_id=document_id, status="pending")


@documents_router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: str,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    database: Annotated[Database[dict[str, Any]], Depends(get_database)],
    request: Request,
) -> None:
    document = await get_document(database, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    group, role = await _require_group(database, str(document["group_id"]), current_user.id)
    if str(document["uploader_id"]) != current_user.id and role != "admin":
        raise HTTPException(status_code=403, detail="Only the uploader or a group admin can delete this document")
    settings: Settings = request.app.state.settings
    service = _processing_service(database, settings)
    try:
        await service.delete_vectors(
            group_id=str(group["_id"]),
            document_id=document_id,
        )
        await LocalDocumentStorage(settings).delete(document["storage_key"])
        await database["documents"].delete_one({"_id": document["_id"]})
    except Exception as exc:
        logger.exception(
            "Document deletion failed",
            extra={"document_id": document_id, "error_type": type(exc).__name__},
        )
        raise HTTPException(status_code=503, detail="Document could not be deleted") from None
