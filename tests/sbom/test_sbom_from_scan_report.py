"""`lcc sbom generate` must read the report that `lcc scan --format json` writes.

Regression test: in 2.0.1 the SBOM generators only understood the ScanResult
shape, so a ScanReport (``findings`` and ``summary``) produced an SBOM with zero
components while the CLI reported success.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from lcc import __version__
from lcc.models import (
    Component,
    ComponentFinding,
    ComponentType,
    LicenseEvidence,
    ScanReport,
    ScanSummary,
    Status,
)
from lcc.reporting.json_reporter import JSONReporter, deserialize_scan_result
from lcc.sbom.cyclonedx import CycloneDXGenerator
from lcc.sbom.spdx import SPDXGenerator


@pytest.fixture
def scan_report_path(tmp_path: Path) -> Path:
    """Write a ScanReport exactly as `lcc scan --format json` does."""
    findings = [
        ComponentFinding(
            component=Component(type=ComponentType.PYTHON, name="numpy", version="2.1.3"),
            evidences=[LicenseEvidence(source="registry", license_expression="BSD-3-Clause", confidence=0.7)],
            resolved_license="BSD-2-Clause AND BSD-3-Clause",
            confidence=0.7,
        ),
        ComponentFinding(
            component=Component(type=ComponentType.PYTHON, name="xgboost", version="2.1.3"),
            resolved_license="Apache-2.0",
            confidence=0.7,
        ),
        ComponentFinding(
            component=Component(type=ComponentType.PYTHON, name="mystery", version="0.1.0"),
            resolved_license=None,
        ),
    ]
    report = ScanReport(
        findings=findings,
        summary=ScanSummary(component_count=3, violations=0, generated_at=datetime(2026, 10, 4, 8, 0, 0)),
    )
    path = tmp_path / "scan-report.json"
    path.write_text(JSONReporter().render(report), encoding="utf-8")
    return path


def test_deserialize_scan_report_keeps_every_finding(scan_report_path: Path) -> None:
    result = deserialize_scan_result(json.loads(scan_report_path.read_text()))

    assert [c.name for c in result.components] == ["numpy", "xgboost", "mystery"]
    statuses = {cr.component.name: cr.status for cr in result.component_results}
    assert statuses == {"numpy": Status.PASS, "xgboost": Status.PASS, "mystery": Status.WARNING}
    assert result.timestamp == datetime(2026, 10, 4, 8, 0, 0)


def test_deserialize_rejects_unknown_shape() -> None:
    with pytest.raises(ValueError, match="Not an LCC scan result"):
        deserialize_scan_result({"unexpected": []})


def test_cyclonedx_from_scan_report(scan_report_path: Path, tmp_path: Path) -> None:
    out = tmp_path / "sbom.cdx.json"
    CycloneDXGenerator().generate_from_file(
        scan_result_path=scan_report_path,
        output_path=out,
        project_name="loan-scoring-model",
        project_version="2.1.0",
    )
    bom = json.loads(out.read_text())

    assert len(bom["components"]) == 3
    by_name = {c["name"]: c for c in bom["components"]}
    assert by_name["xgboost"]["licenses"] == [{"license": {"id": "Apache-2.0"}}]
    assert by_name["numpy"]["licenses"] == [{"expression": "BSD-2-Clause AND BSD-3-Clause"}]
    assert "licenses" not in by_name["mystery"]
    assert bom["metadata"]["component"]["name"] == "loan-scoring-model"
    assert bom["metadata"]["component"]["version"] == "2.1.0"
    assert bom["metadata"]["tools"][0]["version"] == __version__


def test_spdx_from_scan_report(scan_report_path: Path, tmp_path: Path) -> None:
    out = tmp_path / "sbom.spdx.json"
    SPDXGenerator().generate_from_file(
        scan_result_path=scan_report_path,
        output_path=out,
        project_name="loan-scoring-model",
        project_version="2.1.0",
    )
    document = json.loads(out.read_text())

    names = {p["name"] for p in document["packages"]}
    assert {"numpy", "xgboost", "mystery"} <= names
    assert any(__version__ in creator for creator in document["creationInfo"]["creators"])


def test_cyclonedx_project_depends_on_scanned_components(scan_report_path: Path, tmp_path: Path) -> None:
    out = tmp_path / "sbom.cdx.json"
    CycloneDXGenerator().generate_from_file(
        scan_result_path=scan_report_path, output_path=out, project_name="loan-scoring-model"
    )
    bom = json.loads(out.read_text())

    root_ref = bom["metadata"]["component"]["bom-ref"]
    root = next(d for d in bom["dependencies"] if d["ref"] == root_ref)
    assert len(root["dependsOn"]) == 3
