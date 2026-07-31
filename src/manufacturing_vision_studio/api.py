"""Loopback-first FastAPI surface for the local inspection workbench."""

from __future__ import annotations

import stat
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, File, Form, Header, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, model_validator
from starlette.middleware.base import RequestResponseEndpoint
from starlette.types import Scope

from manufacturing_vision_studio import __version__
from manufacturing_vision_studio.adapters import FreeCADExportAdapter
from manufacturing_vision_studio.config import Settings
from manufacturing_vision_studio.demo import seed_demo
from manufacturing_vision_studio.e1.artifacts import (
    ArtifactRecord,
    E1ArtifactError,
    E1ArtifactStore,
)
from manufacturing_vision_studio.e1.runner import verify_e1_results
from manufacturing_vision_studio.errors import MVSError, NotFoundError, UnsafeInputError
from manufacturing_vision_studio.evidence import EvidenceService
from manufacturing_vision_studio.images import ImageIngestor
from manufacturing_vision_studio.registry import LIMITATION, CaseRegistry

_E1_GALLERY_ASSET_FIELDS = (
    "reference_image_url",
    "inspection_image_url",
    "authoritative_mask_url",
    "predicted_mask_url",
    "overlay_url",
)
_MISSING_ARTIFACT_MESSAGES = frozenset({"Artifact is missing", "Artifact parent is missing"})


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CaseCreate(StrictModel):
    part_id: str = Field(min_length=1, max_length=128)
    cad_revision: str | None = Field(default=None, min_length=1, max_length=128)
    revision: str | None = Field(default=None, min_length=1, max_length=128)
    locale: str = "en"

    @model_validator(mode="after")
    def resolve_revision(self) -> CaseCreate:
        if (self.cad_revision is None) == (self.revision is None):
            raise ValueError("Provide exactly one of cad_revision or revision")
        return self

    @property
    def resolved_revision(self) -> str:
        return self.cad_revision or self.revision or ""


class AnalyzeRequest(StrictModel):
    image_id: str | None = Field(default=None, min_length=1, max_length=128)


class DispositionRequest(StrictModel):
    analysis_id: str = Field(min_length=1, max_length=128)
    decision: Literal["accept", "reject", "needs_review", "model_error"]
    reviewer_id: str = Field(min_length=1, max_length=128)
    reviewer_display_name: str | None = Field(default=None, min_length=1, max_length=128)
    reason_codes: list[str] = Field(min_length=1, max_length=16)
    rationale: str = Field(min_length=1, max_length=2000)


class ExportRequest(StrictModel):
    pass


class FreeCADImportRequest(StrictModel):
    case_id: str = Field(min_length=1, max_length=128)
    source_root: str = Field(min_length=1, max_length=1000)
    manifest_relative_path: str = Field(
        default="freecad-export-adapter-manifest.json",
        min_length=1,
        max_length=240,
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    active_settings = settings or Settings.from_env()
    registry = CaseRegistry(active_settings)
    ingestor = ImageIngestor(active_settings)
    evidence = EvidenceService(registry, active_settings)
    app = FastAPI(
        title="Manufacturing Vision Studio",
        version=__version__,
        description="Local deterministic demo backend; not production inspection software.",
    )
    app.state.settings = active_settings
    app.state.registry = registry
    app.state.evidence = evidence
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "If-Match"],
    )

    @app.middleware("http")
    async def reject_external_mutation_origins(
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            origin = request.headers.get("origin")
            if origin is not None and not _is_loopback_origin(origin):
                return JSONResponse(
                    status_code=403,
                    content={
                        "error": {
                            "code": "SCHEMA_INVALID",
                            "message": "Cross-origin mutation is not allowed.",
                            "details": {},
                        }
                    },
                )
        return await call_next(request)

    @app.exception_handler(MVSError)
    async def handle_mvs_error(_request: Request, exc: MVSError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _request: Request, _exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "SCHEMA_INVALID",
                    "message": "Request does not satisfy the API schema.",
                    "details": {},
                }
            },
        )

    @app.exception_handler(Exception)
    async def handle_internal_error(_request: Request, _exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "The local service could not complete the request.",
                    "details": {},
                }
            },
        )

    @app.get("/api/health")
    @app.get("/api/v1/health", include_in_schema=False)
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "version": __version__,
            "schema_version": "1.0.0",
            "mode": "local_demo",
            "limitations": [LIMITATION],
        }

    @app.get("/api/v1/e1/evaluation/latest")
    def get_latest_e1_evaluation(
        profile: Annotated[Literal["mini", "full"], Query()],
    ) -> dict[str, Any]:
        return _load_e1_evaluation_result(active_settings, profile)

    @app.get("/api/v1/e1/evaluation/assets/{profile}/{case_id}/{filename}")
    def get_e1_evaluation_asset(
        profile: Literal["mini", "full"],
        case_id: str,
        filename: str,
    ) -> Response:
        validated_case_id = _validate_e1_public_segment(case_id)
        validated_filename = _validate_e1_public_segment(filename)
        result = _load_e1_evaluation_result(active_settings, profile)
        expected_url = (
            f"/api/v1/e1/evaluation/assets/{profile}/{validated_case_id}/{validated_filename}"
        )
        declared, source_sha256 = _declared_e1_asset(result, expected_url)
        if not declared:
            raise NotFoundError("E1 evaluation asset was not found")
        store = _e1_artifact_store(
            active_settings,
            profile,
            missing_message="E1 evaluation asset was not found",
        )
        inventory = _load_e1_inventory(
            store,
            missing_message="E1 evaluation asset was not found",
        )
        relative_path = f"assets/{validated_case_id}/{validated_filename}"
        record = inventory.get(relative_path)
        if record is None:
            raise NotFoundError("E1 evaluation asset was not found")
        if record.media_type != "image/png" or Path(record.path).suffix.lower() != ".png":
            raise UnsafeInputError(
                "Only PNG E1 evaluation assets may be served.",
                code="SCHEMA_INVALID",
            )
        if source_sha256 is not None and record.sha256 != source_sha256:
            raise E1ArtifactError(
                "E1 evaluation asset does not match its declared source hash",
                code="HASH_MISMATCH",
            )
        try:
            data = store.read_bytes(relative_path, expected_sha256=record.sha256)
        except E1ArtifactError as exc:
            _raise_e1_not_found(exc, "E1 evaluation asset was not found")
            raise
        ingestor.ingest_bytes(
            data,
            filename=validated_filename,
            declared_media_type="image/png",
        )
        return Response(data, media_type="image/png", headers={"Cache-Control": "no-store"})

    @app.get("/api/cases")
    @app.get("/api/v1/cases", include_in_schema=False)
    def list_cases() -> dict[str, Any]:
        return {"items": registry.list_cases()}

    @app.post("/api/cases", status_code=201)
    @app.post("/api/v1/cases", status_code=201, include_in_schema=False)
    def create_case(body: CaseCreate) -> dict[str, Any]:
        return registry.create_case(
            part_id=body.part_id,
            cad_revision=body.resolved_revision,
            locale=body.locale,
        )

    @app.get("/api/cases/{case_id}")
    @app.get("/api/v1/cases/{case_id}", include_in_schema=False)
    def get_case(case_id: str) -> dict[str, Any]:
        return registry.get_case_detail(case_id)

    @app.post("/api/cases/{case_id}/reference", status_code=201)
    async def upload_reference(
        case_id: str,
        file: Annotated[UploadFile, File()],
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> dict[str, Any]:
        revision = _parse_if_match(if_match)
        image = ingestor.ingest_bytes(
            await _bounded_upload(file, active_settings.max_image_bytes),
            filename=file.filename or "upload",
            declared_media_type=file.content_type,
        )
        registry.add_reference(case_id, image, expected_case_revision=revision)
        return registry.get_case_detail(case_id)

    @app.post("/api/cases/{case_id}/images", status_code=201)
    async def upload_inspection(
        case_id: str,
        file: Annotated[UploadFile, File()],
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> dict[str, Any]:
        revision = _parse_if_match(if_match)
        image = ingestor.ingest_bytes(
            await _bounded_upload(file, active_settings.max_image_bytes),
            filename=file.filename or "upload",
            declared_media_type=file.content_type,
        )
        registry.add_inspection(case_id, image, expected_case_revision=revision)
        return registry.get_case_detail(case_id)

    @app.post("/api/v1/cases/{case_id}/images", status_code=201, include_in_schema=False)
    async def upload_v1_image(
        case_id: str,
        file: Annotated[UploadFile, File()],
        role: Annotated[Literal["reference", "inspection"], Form()],
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> dict[str, Any]:
        revision = _parse_if_match(if_match)
        image = ingestor.ingest_bytes(
            await _bounded_upload(file, active_settings.max_image_bytes),
            filename=file.filename or "upload",
            declared_media_type=file.content_type,
        )
        document = (
            registry.add_reference(case_id, image, expected_case_revision=revision)
            if role == "reference"
            else registry.add_inspection(case_id, image, expected_case_revision=revision)
        )
        del document
        return registry.get_case_detail(case_id)

    @app.post("/api/cases/{case_id}/analyze")
    @app.post("/api/v1/cases/{case_id}/analyses", include_in_schema=False)
    def analyze(
        case_id: str,
        body: AnalyzeRequest,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> dict[str, Any]:
        results = registry.analyze_case(
            case_id,
            image_id=body.image_id,
            expected_case_revision=_parse_if_match(if_match),
        )
        del results
        return registry.get_case_detail(case_id)

    @app.post("/api/cases/{case_id}/disposition", status_code=201)
    @app.post("/api/v1/cases/{case_id}/dispositions", status_code=201, include_in_schema=False)
    def disposition(
        case_id: str,
        body: DispositionRequest,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> dict[str, Any]:
        document = registry.add_disposition(
            case_id,
            analysis_id=body.analysis_id,
            decision=body.decision,
            reviewer_id=body.reviewer_id,
            reviewer_display_name=body.reviewer_display_name,
            reason_codes=body.reason_codes,
            rationale=body.rationale,
            expected_case_revision=_parse_if_match(if_match),
        )
        del document
        return registry.get_case_detail(case_id)

    @app.post("/api/cases/{case_id}/export", status_code=201)
    @app.post("/api/v1/cases/{case_id}/exports", status_code=201, include_in_schema=False)
    def export_case(
        case_id: str,
        _body: ExportRequest,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> dict[str, Any]:
        result = evidence.export_case(
            case_id,
            expected_case_revision=_parse_if_match(if_match),
        )
        return {
            "bundle_id": result.manifest["bundle_id"],
            "bundle_sha256": result.bundle_sha256,
            "manifest": result.manifest,
            "download_url": f"/api/exports/{result.path.name}",
        }

    @app.get("/api/exports/{filename}")
    def download_export(filename: str) -> FileResponse:
        if Path(filename).name != filename or not re_fullmatch_bundle(filename):
            raise UnsafeInputError("Export filename is unsafe", code="UNSAFE_PATH")
        path = active_settings.export_dir / filename
        if path.is_symlink() or not path.is_file():
            from manufacturing_vision_studio.errors import NotFoundError

            raise NotFoundError("Evidence export was not found")
        return FileResponse(path, media_type="application/zip", filename=filename)

    @app.post("/api/evidence/verify")
    @app.post("/api/v1/bundles/verify", include_in_schema=False)
    async def verify_bundle(
        file: Annotated[UploadFile, File()],
        expected_part_id: Annotated[str | None, Form()] = None,
        expected_cad_revision: Annotated[str | None, Form()] = None,
    ) -> dict[str, Any]:
        data = await _bounded_upload(file, active_settings.max_bundle_bytes)
        return evidence.verify_bundle(
            data,
            expected_part_id=expected_part_id,
            expected_cad_revision=expected_cad_revision,
        ).as_dict()

    @app.post("/api/evidence/import", status_code=201)
    async def import_bundle(file: Annotated[UploadFile, File()]) -> dict[str, Any]:
        data = await _bounded_upload(file, active_settings.max_bundle_bytes)
        return evidence.import_bundle(data).as_dict()

    @app.post("/api/v1/freecad-exports/import", status_code=201)
    def import_freecad_reference(
        body: FreeCADImportRequest,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> dict[str, Any]:
        return FreeCADExportAdapter(active_settings).import_reference(
            registry,
            body.case_id,
            Path(body.source_root),
            expected_case_revision=_parse_if_match(if_match),
            manifest_relative_path=body.manifest_relative_path,
        )

    @app.get("/api/images/{image_id}")
    def image_content(
        image_id: str,
        canonical: Annotated[bool, Query()] = False,
    ) -> Response:
        data, media_type = registry.get_image_bytes(image_id, canonical=canonical)
        return Response(data, media_type=media_type, headers={"Cache-Control": "no-store"})

    @app.get("/api/analyses/{analysis_id}/mask")
    def mask_content(analysis_id: str) -> Response:
        data, media_type = registry.get_analysis_artifact(analysis_id, "mask")
        return Response(data, media_type=media_type, headers={"Cache-Control": "no-store"})

    @app.get("/api/analyses/{analysis_id}/registered")
    def registered_content(analysis_id: str) -> Response:
        data, media_type = registry.get_analysis_artifact(analysis_id, "registered")
        return Response(data, media_type=media_type, headers={"Cache-Control": "no-store"})

    @app.post("/api/demo")
    def create_demo() -> dict[str, Any]:
        return seed_demo(registry, reset=False)

    @app.post("/api/demo/reset")
    def reset_demo() -> dict[str, Any]:
        return seed_demo(registry, reset=True)

    _mount_web_if_present(app)
    return app


async def _bounded_upload(file: UploadFile, limit: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(min(1024 * 1024, limit + 1 - total))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > limit:
            raise UnsafeInputError("Upload exceeds byte limit", code="INPUT_TOO_LARGE")
    return b"".join(chunks)


def _parse_if_match(value: str | None) -> int:
    if value is None or not value.isascii() or not value.isdigit():
        raise UnsafeInputError(
            "A numeric If-Match case revision is required.",
            code="SCHEMA_INVALID",
        )
    parsed = int(value)
    if parsed < 1:
        raise UnsafeInputError("Case revision is invalid.", code="SCHEMA_INVALID")
    return parsed


def _is_loopback_origin(origin: str) -> bool:
    if not origin.isascii() or any(character.isspace() for character in origin):
        return False
    try:
        parsed = urlsplit(origin)
        port = parsed.port
    except ValueError:
        return False
    del port
    return (
        parsed.scheme in {"http", "https"}
        and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        and parsed.username is None
        and parsed.password is None
        and parsed.path == ""
        and parsed.query == ""
        and parsed.fragment == ""
    )


def re_fullmatch_bundle(filename: str) -> bool:
    import re

    return re.fullmatch(r"bundle-[a-f0-9]{24}\.zip", filename) is not None


class SPAStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        if response.status_code == 404 and not path.startswith("api/"):
            return await super().get_response("index.html", scope)
        return response


def _mount_web_if_present(app: FastAPI) -> None:
    web_dist = Path(__file__).resolve().parents[2] / "web" / "dist"
    if web_dist.is_dir() and (web_dist / "index.html").is_file():
        app.mount("/", SPAStaticFiles(directory=web_dist, html=True), name="web")


app = create_app()


def _load_e1_evaluation_result(
    settings: Settings, profile: Literal["mini", "full"]
) -> dict[str, Any]:
    store = _e1_artifact_store(
        settings,
        profile,
        missing_message="E1 evaluation result was not found",
    )
    try:
        result = verify_e1_results(store.root)
    except E1ArtifactError as exc:
        _raise_e1_not_found(exc, "E1 evaluation result was not found")
        raise
    if result.get("profile") != profile:
        raise E1ArtifactError(
            "E1 artifact profile does not match the request",
            code="SCHEMA_INVALID",
        )
    result.pop("local_absolute_paths", None)
    return result


def _e1_artifact_store(
    settings: Settings,
    profile: Literal["mini", "full"],
    *,
    missing_message: str,
) -> E1ArtifactStore:
    data_root = _existing_directory(
        settings.data_dir,
        missing_message=missing_message,
    )
    profile_root = _existing_directory(
        data_root / "e1-evaluation" / profile,
        missing_message=missing_message,
    )
    return E1ArtifactStore(profile_root, allowed_root=data_root)


def _existing_directory(path: Path, *, missing_message: str) -> Path:
    expanded = path.expanduser()
    absolute = expanded if expanded.is_absolute() else (Path.cwd() / expanded)
    absolute = absolute.absolute()
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        try:
            metadata = current.lstat()
        except FileNotFoundError as exc:
            raise NotFoundError(missing_message) from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise E1ArtifactError("Artifact path contains a symlink", code="SYMLINK_INPUT")
        if not stat.S_ISDIR(metadata.st_mode):
            raise E1ArtifactError("Artifact path is not a directory", code="NON_REGULAR_INPUT")
    return absolute.resolve(strict=True)


def _load_e1_inventory(
    store: E1ArtifactStore, *, missing_message: str
) -> dict[str, ArtifactRecord]:
    try:
        return {record.path: record for record in store.verify_inventory("inventory.json")}
    except E1ArtifactError as exc:
        _raise_e1_not_found(exc, missing_message)
        raise


def _declared_e1_asset(result: dict[str, Any], expected_url: str) -> tuple[bool, str | None]:
    source_hash_fields = {
        "reference_image_url": "reference_sha256",
        "inspection_image_url": "inspection_sha256",
        "authoritative_mask_url": "authoritative_mask_sha256",
        "predicted_mask_url": "predicted_mask_sha256",
        "overlay_url": None,
    }
    for item in result.get("error_gallery", []):
        if not isinstance(item, dict):
            continue
        assets = item.get("assets")
        hashes = item.get("source_hashes")
        if not isinstance(assets, dict) or not isinstance(hashes, dict):
            continue
        for field_name in _E1_GALLERY_ASSET_FIELDS:
            if assets.get(field_name) != expected_url:
                continue
            hash_field = source_hash_fields[field_name]
            source_sha256 = hashes.get(hash_field) if hash_field is not None else None
            return True, source_sha256 if isinstance(source_sha256, str) else None
    return False, None


def _validate_e1_public_segment(value: str) -> str:
    if (
        not value
        or value in {".", ".."}
        or Path(value).name != value
        or "/" in value
        or "\\" in value
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise UnsafeInputError("E1 artifact path is unsafe", code="UNSAFE_PATH")
    return value


def _raise_e1_not_found(exc: E1ArtifactError, missing_message: str) -> None:
    if exc.code == "EVIDENCE_INCOMPLETE" and exc.message in _MISSING_ARTIFACT_MESSAGES:
        raise NotFoundError(missing_message) from exc
