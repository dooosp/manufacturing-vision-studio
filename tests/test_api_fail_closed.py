from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from manufacturing_vision_studio.api import create_app
from manufacturing_vision_studio.config import Settings


def png_bytes() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (8, 6), (20, 40, 60)).save(output, format="PNG")
    return output.getvalue()


def create_case(client: TestClient) -> dict[str, Any]:
    response = client.post(
        "/api/cases",
        json={"part_id": "PART-API", "cad_revision": "A", "locale": "en"},
    )
    assert response.status_code == 201
    return response.json()


def assert_error_envelope(response: Any, code: str) -> dict[str, Any]:
    payload = response.json()
    assert set(payload) == {"error"}
    assert set(payload["error"]) == {"code", "message", "details"}
    assert payload["error"]["code"] == code
    assert isinstance(payload["error"]["message"], str)
    assert isinstance(payload["error"]["details"], dict)
    serialized = json.dumps(payload)
    assert "Traceback" not in serialized
    assert "/Users/" not in serialized
    assert "sqlite" not in serialized.lower()
    return payload


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(Settings(data_dir=tmp_path / "data")))


def test_missing_if_match_fails_closed_as_invalid_request(client: TestClient) -> None:
    created = create_case(client)
    case_id = created["case"]["case_id"]

    response = client.post(
        f"/api/cases/{case_id}/reference",
        files={"file": ("reference.png", png_bytes(), "image/png")},
    )
    malformed = client.post(
        f"/api/cases/{case_id}/reference",
        headers={"If-Match": "not-a-revision"},
        files={"file": ("reference.png", png_bytes(), "image/png")},
    )

    assert response.status_code == 422
    assert_error_envelope(response, "SCHEMA_INVALID")
    assert malformed.status_code == 422
    assert_error_envelope(malformed, "SCHEMA_INVALID")
    detail = client.get(f"/api/cases/{case_id}").json()
    assert detail["case"]["case_revision"] == 1
    assert detail["images"] == []


def test_stale_revision_upload_publishes_no_image_or_revision_change(client: TestClient) -> None:
    created = create_case(client)
    case_id = created["case"]["case_id"]
    accepted = client.post(
        f"/api/cases/{case_id}/reference",
        headers={"If-Match": "1"},
        files={"file": ("reference.png", png_bytes(), "image/png")},
    )
    assert accepted.status_code == 201

    stale = client.post(
        f"/api/cases/{case_id}/images",
        headers={"If-Match": "1"},
        files={"file": ("inspection.png", png_bytes(), "image/png")},
    )

    assert stale.status_code == 409
    details = assert_error_envelope(stale, "REVISION_MISMATCH")["error"]["details"]
    assert details["expected_case_revision"] == 1
    assert details["actual_case_revision"] == 2
    detail = client.get(f"/api/cases/{case_id}").json()
    assert detail["case"]["case_revision"] == 2
    assert [image["role"] for image in detail["images"]] == ["reference"]
    assert detail["analyses"] == []
    assert detail["dispositions"] == []


def test_malformed_and_traversal_named_uploads_are_rejected_without_stack_trace(
    client: TestClient,
) -> None:
    created = create_case(client)
    case_id = created["case"]["case_id"]

    malformed = client.post(
        f"/api/cases/{case_id}/reference",
        headers={"If-Match": "1"},
        files={"file": ("reference.png", b"not-an-image", "image/png")},
    )
    traversal = client.post(
        f"/api/cases/{case_id}/reference",
        headers={"If-Match": "1"},
        files={"file": ("../reference.png", png_bytes(), "image/png")},
    )

    assert malformed.status_code == 422
    assert_error_envelope(malformed, "IMAGE_DECODE_FAILED")
    assert traversal.status_code == 422
    assert_error_envelope(traversal, "UNSAFE_PATH")
    assert client.get(f"/api/cases/{case_id}").json()["images"] == []


def test_missing_reference_analysis_returns_machine_code_and_no_result(client: TestClient) -> None:
    created = create_case(client)
    case_id = created["case"]["case_id"]

    response = client.post(
        f"/api/cases/{case_id}/analyze",
        headers={"If-Match": "1"},
        json={},
    )

    assert response.status_code == 422
    assert_error_envelope(response, "MISSING_REFERENCE")
    detail = client.get(f"/api/cases/{case_id}").json()
    assert detail["analyses"] == []
    assert detail["case"]["case_revision"] == 1


def test_upload_byte_limit_is_enforced_before_image_decode(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data", max_image_bytes=64)
    client = TestClient(create_app(settings))
    created = create_case(client)
    case_id = created["case"]["case_id"]

    response = client.post(
        f"/api/cases/{case_id}/reference",
        headers={"If-Match": "1"},
        files={"file": ("oversized.png", b"x" * 65, "image/png")},
    )

    assert response.status_code == 422
    assert_error_envelope(response, "INPUT_TOO_LARGE")
    assert client.get(f"/api/cases/{case_id}").json()["images"] == []


def test_request_schema_rejects_unknown_fields(client: TestClient) -> None:
    response = client.post(
        "/api/cases",
        json={
            "part_id": "PART-API",
            "cad_revision": "A",
            "locale": "en",
            "production_override": True,
        },
    )

    assert response.status_code == 422
    assert_error_envelope(response, "SCHEMA_INVALID")


@pytest.mark.parametrize(
    "origin",
    [
        "https://attacker.example",
        "null",
        "http://localhost.attacker.example",
        "https://127.0.0.1.attacker.example:8443",
    ],
)
def test_external_mutation_origins_are_rejected_without_state_change(
    client: TestClient,
    origin: str,
) -> None:
    response = client.post(
        "/api/cases",
        headers={"Origin": origin},
        json={"part_id": "PART-ORIGIN", "cad_revision": "A", "locale": "en"},
    )

    assert response.status_code == 403
    assert_error_envelope(response, "SCHEMA_INVALID")
    assert client.get("/api/cases").json() == {"items": []}


@pytest.mark.parametrize(
    "origin",
    [
        None,
        "http://localhost:4173",
        "https://127.0.0.1:8443",
        "http://[::1]:4173",
    ],
)
def test_cli_and_loopback_mutation_origins_are_allowed(
    client: TestClient,
    origin: str | None,
) -> None:
    headers = {} if origin is None else {"Origin": origin}

    response = client.post(
        "/api/cases",
        headers=headers,
        json={"part_id": "PART-ORIGIN", "cad_revision": "A", "locale": "en"},
    )

    assert response.status_code == 201
    detail = response.json()
    assert detail["case"]["part_identity"] == {
        "part_id": "PART-ORIGIN",
        "cad_revision": "A",
    }
