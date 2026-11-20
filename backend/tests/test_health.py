import httpx
import pytest

from app.api.v1.endpoints import health
from app.main import create_app


@pytest.mark.asyncio
async def test_health_reports_application_and_database_status(monkeypatch) -> None:
    async def database_is_connected(client) -> bool:
        return True

    monkeypatch.setattr(health, "check_mongodb_connection", database_is_connected)
    app = create_app()

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.get("/api/v1/health")
            docs_response = await client.get("/docs")
            openapi_response = await client.get("/openapi.json")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "mongodb": "connected"}
    assert docs_response.status_code == 200
    assert "/api/v1/health" in openapi_response.json()["paths"]


@pytest.mark.asyncio
async def test_health_reports_database_unavailable(monkeypatch) -> None:
    async def database_is_disconnected(client) -> bool:
        return False

    monkeypatch.setattr(health, "check_mongodb_connection", database_is_disconnected)
    app = create_app()

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.get("/api/v1/health")

    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "mongodb": "disconnected"}
