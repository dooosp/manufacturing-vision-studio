"""Subprocess contracts for the package import boundary used by the E1 study."""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

ROOT_EXPORTS = (
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
)

E1_EXPORTS = (
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
)


def _run_isolated(source: str) -> None:
    env = os.environ.copy()
    python_path = str(PROJECT_ROOT / "src")
    if existing := env.get("PYTHONPATH"):
        python_path = os.pathsep.join((python_path, existing))
    env["PYTHONPATH"] = python_path
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(source)],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_root_import_has_minimal_runtime_closure_and_unchanged_public_surface() -> None:
    """Catch root initialization that eagerly reaches adapter or persistence modules."""

    _run_isolated(
        f"""
        import sys
        import manufacturing_vision_studio as package

        forbidden = {{
            "manufacturing_vision_studio.adapters",
            "manufacturing_vision_studio.config",
            "manufacturing_vision_studio.evidence",
            "manufacturing_vision_studio.registry",
        }}
        assert forbidden.isdisjoint(sys.modules), forbidden & sys.modules.keys()
        assert tuple(package.__all__) == {ROOT_EXPORTS!r}
        assert set(package.__all__) <= set(dir(package))
        """
    )


def test_e1_import_keeps_only_domain_exports_eager() -> None:
    """Catch E1 initialization that eagerly reaches generators, oracles, or protocols."""

    _run_isolated(
        f"""
        import sys
        import manufacturing_vision_studio.e1 as package

        assert "manufacturing_vision_studio.e1.domain" in sys.modules
        forbidden = {{
            "manufacturing_vision_studio.e1.generator",
            "manufacturing_vision_studio.e1.oracle",
            "manufacturing_vision_studio.e1.protocol",
        }}
        assert forbidden.isdisjoint(sys.modules), forbidden & sys.modules.keys()
        assert tuple(package.__all__) == {E1_EXPORTS!r}
        assert set(package.__all__) <= set(dir(package))
        """
    )


def test_root_lazy_exports_preserve_identity_and_cache_on_first_access() -> None:
    """Catch a lazy root lookup returning wrappers or repeating import resolution."""

    _run_isolated(
        """
        import importlib
        import manufacturing_vision_studio as package

        exports = {
            "CaseRegistry": ("manufacturing_vision_studio.registry", "CaseRegistry"),
            "DeterministicDifferenceModel": (
                "manufacturing_vision_studio.model",
                "DeterministicDifferenceModel",
            ),
            "EvidenceService": ("manufacturing_vision_studio.evidence", "EvidenceService"),
            "FreeCADExportAdapter": (
                "manufacturing_vision_studio.adapters",
                "FreeCADExportAdapter",
            ),
            "ImageIngestor": ("manufacturing_vision_studio.images", "ImageIngestor"),
            "IngestedImage": ("manufacturing_vision_studio.images", "IngestedImage"),
            "InspectionResult": ("manufacturing_vision_studio.model", "InspectionResult"),
            "MVTecADAdapter": ("manufacturing_vision_studio.adapters", "MVTecADAdapter"),
            "ModelConfig": ("manufacturing_vision_studio.model", "ModelConfig"),
            "Settings": ("manufacturing_vision_studio.config", "Settings"),
            "VerificationResult": (
                "manufacturing_vision_studio.evidence",
                "VerificationResult",
            ),
        }
        for name, (module_name, attribute_name) in exports.items():
            assert name not in package.__dict__
            value = getattr(package, name)
            expected = getattr(importlib.import_module(module_name), attribute_name)
            assert value is expected
            assert package.__dict__[name] is expected
            assert getattr(package, name) is value
        """
    )


def test_e1_lazy_exports_preserve_identity_and_cache_on_first_access() -> None:
    """Catch lazy E1 lookups that change the established exported objects."""

    _run_isolated(
        """
        import importlib
        import manufacturing_vision_studio.e1 as package

        exports = {
            "E1Generator": ("manufacturing_vision_studio.e1.generator", "E1Generator"),
            "plan_e1_cases": ("manufacturing_vision_studio.e1.generator", "plan_e1_cases"),
            "plan_e1_full": ("manufacturing_vision_studio.e1.generator", "plan_e1_full"),
            "render_e1_case": ("manufacturing_vision_studio.e1.generator", "render_e1_case"),
            "select_e1_profile": (
                "manufacturing_vision_studio.e1.generator",
                "select_e1_profile",
            ),
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
            "DEFAULT_E1_CONFIG_PATH": (
                "manufacturing_vision_studio.e1.protocol",
                "DEFAULT_E1_CONFIG_PATH",
            ),
            "E1Protocol": ("manufacturing_vision_studio.e1.protocol", "E1Protocol"),
            "E1ProtocolError": (
                "manufacturing_vision_studio.e1.protocol",
                "E1ProtocolError",
            ),
            "load_e1_protocol": (
                "manufacturing_vision_studio.e1.protocol",
                "load_e1_protocol",
            ),
        }
        for name, (module_name, attribute_name) in exports.items():
            assert name not in package.__dict__
            value = getattr(package, name)
            expected = getattr(importlib.import_module(module_name), attribute_name)
            assert value is expected
            assert package.__dict__[name] is expected
            assert getattr(package, name) is value
        """
    )


def test_unknown_package_attributes_raise_attribute_error() -> None:
    """Catch lazy lookup hooks that mask misspelled public names."""

    _run_isolated(
        """
        import manufacturing_vision_studio as root
        import manufacturing_vision_studio.e1 as e1

        for package in (root, e1):
            try:
                package.not_a_public_export
            except AttributeError:
                pass
            else:
                raise AssertionError("unknown package attribute did not fail closed")
        """
    )


def test_e1_trust_boundaries_keeps_normal_fromlist_submodule_behavior() -> None:
    """Catch an E1 lazy lookup hook that blocks normal child-module imports."""

    _run_isolated(
        """
        import importlib
        import sys

        from manufacturing_vision_studio.e1 import trust_boundaries

        module_name = "manufacturing_vision_studio.e1.trust_boundaries"
        assert trust_boundaries is importlib.import_module(module_name)
        assert sys.modules[module_name] is trust_boundaries
        """
    )
