"""Loopback-first FastAPI surface for the local inspection workbench."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import FastAPI, File, Form, Header, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, model_validator
from starlette.types import Scope

from manufacturing_vision_studio import __version__
from manufacturing_vision_studio.adapters import FreeCADExportAdapter
from manufacturing_vision_studio.config import Settings
from manufacturing_vision_studio.demo import seed_demo
from manufacturing_vision_studio.errors import MVSError, UnsafeInputError
from manufacturing_vision_studio.evidence import EvidenceService
from manufacturing_vision_studio.images import ImageIngestor
from manufacturing_vision_studio.registry import LIMITATION, CaseRegistry


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
