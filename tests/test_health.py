"""Smoke test — l'app demarre et /health repond."""
import pytest


@pytest.mark.asyncio
async def test_health(client):
    res = await client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["app"] == "E-discussion"


@pytest.mark.asyncio
async def test_root_lists_locales(client):
    res = await client.get("/")
    assert res.status_code == 200
    assert "fr" in res.json()["locales"]


@pytest.mark.asyncio
async def test_i18n_error_language(client):
    """Une 401 renvoyee en anglais si Accept-Language: en."""
    res = await client.get("/api/v1/auth/me", headers={"Accept-Language": "en"})
    assert res.status_code == 401
    assert res.json()["detail"]["message"] == "Authentication required."

    res_fr = await client.get("/api/v1/auth/me", headers={"Accept-Language": "fr"})
    assert res_fr.json()["detail"]["message"] == "Authentification requise."
