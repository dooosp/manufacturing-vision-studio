"""Public generator and oracle contracts for E1 synthetic evaluation."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

from manufacturing_vision_studio.e1.domain import (
    AuthoritativeMaskValidation,
    CadRevision,
    CaseGroup,
    DatasetProfile,
    DatasetSplit,
    DefectSpec,
    DefectType,
    E1CasePlan,
    E1GeneratedCase,
    ExpectedOutcome,
    NuisanceSpec,
    NuisanceType,
    RecipeParameter,
    Severity,
    SupportBoundary,
    TrustBoundarySpec,
    ViewId,
)

if TYPE_CHECKING:
    from manufacturing_vision_studio.e1.generator import (
        E1Generator,
        plan_e1_cases,
        plan_e1_full,
        render_e1_case,
        select_e1_profile,
    )
    from manufacturing_vision_studio.e1.oracle import (
        validate_authoritative_mask,
        validate_authoritative_truth,
        validate_generated_case,
    )
    from manufacturing_vision_studio.e1.protocol import (
        DEFAULT_E1_CONFIG_PATH,
        E1Protocol,
        E1ProtocolError,
        load_e1_protocol,
    )

__all__ = [
    "DEFAULT_E1_CONFIG_PATH",
    "AuthoritativeMaskValidation",
    "CadRevision",
    "CaseGroup",
    "DatasetProfile",
    "DatasetSplit",
    "DefectSpec",
    "DefectType",
    "E1CasePlan",
    "E1GeneratedCase",
    "E1Generator",
    "E1Protocol",
    "E1ProtocolError",
    "ExpectedOutcome",
    "NuisanceSpec",
    "NuisanceType",
    "RecipeParameter",
    "Severity",
    "SupportBoundary",
    "TrustBoundarySpec",
    "ViewId",
    "load_e1_protocol",
    "plan_e1_cases",
    "plan_e1_full",
    "render_e1_case",
    "select_e1_profile",
    "validate_authoritative_mask",
    "validate_authoritative_truth",
    "validate_generated_case",
]

_LAZY_EXPORTS = {
    "DEFAULT_E1_CONFIG_PATH": (
        "manufacturing_vision_studio.e1.protocol",
        "DEFAULT_E1_CONFIG_PATH",
    ),
    "E1Generator": ("manufacturing_vision_studio.e1.generator", "E1Generator"),
    "E1Protocol": ("manufacturing_vision_studio.e1.protocol", "E1Protocol"),
    "E1ProtocolError": ("manufacturing_vision_studio.e1.protocol", "E1ProtocolError"),
    "load_e1_protocol": ("manufacturing_vision_studio.e1.protocol", "load_e1_protocol"),
    "plan_e1_cases": ("manufacturing_vision_studio.e1.generator", "plan_e1_cases"),
    "plan_e1_full": ("manufacturing_vision_studio.e1.generator", "plan_e1_full"),
    "render_e1_case": ("manufacturing_vision_studio.e1.generator", "render_e1_case"),
    "select_e1_profile": ("manufacturing_vision_studio.e1.generator", "select_e1_profile"),
    "validate_authoritative_mask": (
        "manufacturing_vision_studio.e1.oracle",
        "validate_authoritative_mask",
    ),
    "validate_authoritative_truth": (
        "manufacturing_vision_studio.e1.oracle",
        "validate_authoritative_truth",
    ),
    "validate_generated_case": (
        "manufacturing_vision_studio.e1.oracle",
        "validate_generated_case",
    ),
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
