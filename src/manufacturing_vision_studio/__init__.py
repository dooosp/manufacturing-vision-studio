"""Manufacturing Vision Studio deterministic local backend."""

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
