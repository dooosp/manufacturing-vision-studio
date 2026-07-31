"""Small standard-library CLI for the local demo and evidence workflow."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import NoReturn

import uvicorn

from manufacturing_vision_studio.adapters import FreeCADExportAdapter, MVTecADAdapter
from manufacturing_vision_studio.config import Settings
from manufacturing_vision_studio.demo import seed_demo
from manufacturing_vision_studio.e1.runner import run_e1_evaluation, verify_e1_results
from manufacturing_vision_studio.evidence import EvidenceService
from manufacturing_vision_studio.registry import CaseRegistry


def serve() -> NoReturn:
    parser = argparse.ArgumentParser(description="Run the loopback Manufacturing Vision Studio API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    args = parser.parse_args()
    if args.host not in {"127.0.0.1", "localhost", "::1"}:
        parser.error("Remote binding is outside the supported local demo boundary")
    import os

    os.environ["MVS_DATA_DIR"] = str(args.data_dir)
    uvicorn.run(
        "manufacturing_vision_studio.api:app",
        host=args.host,
        port=args.port,
        reload=False,
    )
    raise SystemExit(0)


def demo() -> None:
    parser = argparse.ArgumentParser(description="Seed deterministic synthetic inspection evidence")
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()
    registry = CaseRegistry(Settings(data_dir=args.data_dir))
    detail = seed_demo(registry, reset=args.reset, seed=args.seed)
    print(json.dumps(detail, ensure_ascii=False, indent=2))


def evidence() -> None:
    parser = argparse.ArgumentParser(description="Export, verify, or import local evidence bundles")
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    subparsers = parser.add_subparsers(dest="command", required=True)
    export_parser = subparsers.add_parser("export")
    export_parser.add_argument("case_id")
    export_parser.add_argument("--expected-revision", type=int, required=True)
    export_parser.add_argument("--output", type=Path)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("bundle", type=Path)
    verify_parser.add_argument("--part-id")
    verify_parser.add_argument("--cad-revision")
    import_parser = subparsers.add_parser("import")
    import_parser.add_argument("bundle", type=Path)
    args = parser.parse_args()
    registry = CaseRegistry(Settings(data_dir=args.data_dir))
    service = EvidenceService(registry)
    if args.command == "export":
        result = service.export_case(
            args.case_id,
            expected_case_revision=args.expected_revision,
            destination=args.output,
        )
        output = result.as_dict()
    elif args.command == "verify":
        output = service.verify_bundle(
            args.bundle,
            expected_part_id=args.part_id,
            expected_cad_revision=args.cad_revision,
        ).as_dict()
    else:
        output = service.import_bundle(args.bundle).as_dict()
    print(json.dumps(output, ensure_ascii=False, indent=2, default=str))


def mvtec() -> None:
    parser = argparse.ArgumentParser(
        description="Validate a caller-provided non-commercial MVTec AD dataset"
    )
    parser.add_argument("dataset_root", type=Path)
    parser.add_argument("category")
    parser.add_argument("--split", choices=["train", "test"], default="test")
    parser.add_argument("--max-samples", type=int, default=1000)
    parser.add_argument("--acknowledge-noncommercial-license", action="store_true")
    args = parser.parse_args()
    if not args.acknowledge_noncommercial_license:
        parser.error("--acknowledge-noncommercial-license is required")
    summary = MVTecADAdapter(
        args.dataset_root,
        noncommercial_license_acknowledged=True,
    ).scan(args.category, split=args.split, max_samples=args.max_samples)
    print(json.dumps(summary.as_dict(), ensure_ascii=False, indent=2))


def freecad() -> None:
    parser = argparse.ArgumentParser(description="Validate or import an inert FreeCAD export")
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("source_root", type=Path)
    validate_parser.add_argument("--manifest", default="freecad-export-adapter-manifest.json")
    import_parser = subparsers.add_parser("import-reference")
    import_parser.add_argument("case_id")
    import_parser.add_argument("source_root", type=Path)
    import_parser.add_argument("--manifest", default="freecad-export-adapter-manifest.json")
    import_parser.add_argument("--expected-revision", type=int, required=True)
    args = parser.parse_args()
    settings = Settings(data_dir=args.data_dir)
    adapter = FreeCADExportAdapter(settings)
    if args.command == "validate":
        output = adapter.validate(
            args.source_root,
            manifest_relative_path=args.manifest,
        ).as_dict()
    else:
        output = adapter.import_reference(
            CaseRegistry(settings),
            args.case_id,
            args.source_root,
            expected_case_revision=args.expected_revision,
            manifest_relative_path=args.manifest,
        )
    print(json.dumps(output, ensure_ascii=False, indent=2))


def e1() -> None:
    """Run or verify the frozen E1 synthetic evaluation artifacts."""

    parser = argparse.ArgumentParser(
        description="Run or verify E1 authoritative synthetic evaluation evidence"
    )
    parser.add_argument("--output-root", type=Path, default=Path("data/e1-evaluation"))
    subparsers = parser.add_subparsers(dest="command", required=True)
    evaluate_parser = subparsers.add_parser("evaluate")
    evaluate_parser.add_argument("--profile", choices=("mini", "full"), required=True)
    evaluate_parser.add_argument("--bootstrap-replicates", type=int, default=10_000)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--profile", choices=("mini", "full"), required=True)
    args = parser.parse_args()

    if args.command == "evaluate":
        output = run_e1_evaluation(
            args.profile,
            args.output_root,
            bootstrap_replicates=args.bootstrap_replicates,
        )
    else:
        output = verify_e1_results(args.output_root / args.profile)
    print(json.dumps(output, ensure_ascii=False, indent=2))
