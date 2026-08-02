"""Manufacturing Vision Studio deterministic local backend."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from manufacturing_vision_studio.adapters import FreeCADExportAdapter, MVTecADAdapter
    from manufacturing_vision_studio.config import Settings
    from manufacturing_vision_studio.evidence import EvidenceService, VerificationResult
    from manufacturing_vision_studio.images import ImageIngestor, IngestedImage
    from manufacturing_vision_studio.model import (
        DeterministicDifferenceModel,
        InspectionResult,
        ModelConfig,
    )
    from manufacturing_vision_studio.registry import CaseRegistry

__all__ = [
    "CaseRegistry",
    "DeterministicDifferenceModel",
    "EvidenceService",
    "FreeCADExportAdapter",
    "ImageIngestor",
    "IngestedImage",
    "InspectionResult",
    "MVTecADAdapter",
    "ModelConfig",
    "Settings",
    "VerificationResult",
]

__version__ = "0.2.0"

_LAZY_EXPORTS = {
    "CaseRegistry": ("manufacturing_vision_studio.registry", "CaseRegistry"),
    "DeterministicDifferenceModel": (
        "manufacturing_vision_studio.model",
        "DeterministicDifferenceModel",
    ),
    "EvidenceService": ("manufacturing_vision_studio.evidence", "EvidenceService"),
    "FreeCADExportAdapter": ("manufacturing_vision_studio.adapters", "FreeCADExportAdapter"),
    "ImageIngestor": ("manufacturing_vision_studio.images", "ImageIngestor"),
    "IngestedImage": ("manufacturing_vision_studio.images", "IngestedImage"),
    "InspectionResult": ("manufacturing_vision_studio.model", "InspectionResult"),
    "MVTecADAdapter": ("manufacturing_vision_studio.adapters", "MVTecADAdapter"),
    "ModelConfig": ("manufacturing_vision_studio.model", "ModelConfig"),
    "Settings": ("manufacturing_vision_studio.config", "Settings"),
    "VerificationResult": ("manufacturing_vision_studio.evidence", "VerificationResult"),
}


def __getattr__(name: str) -> Any:
    try:
        module_name, attribute_name = _LAZY_EXPORTS[name]
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
    value = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
