# Copyright 2025 Ajay Pundhir
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
JSON reporter.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from lcc.models import (
    Component,
    ComponentResult,
    ComponentType,
    LicenseEvidence,
    ScanReport,
    ScanResult,
    Status,
)
from lcc.reporting.base import Reporter


class JSONReporter(Reporter):
    """
    Serializes the ScanReport to JSON, preserving dataclass structure.
    """

    def render(self, report: ScanReport) -> str:
        return json.dumps(asdict(report), indent=2, sort_keys=True, default=str)


def _deserialize_component(comp_data: dict[str, Any]) -> Component:
    return Component(
        type=ComponentType(comp_data["type"]),
        name=comp_data["name"],
        version=comp_data["version"],
        namespace=comp_data.get("namespace"),
        path=Path(comp_data["path"]) if comp_data.get("path") else None,
        metadata=comp_data.get("metadata") or {},
    )


def _scan_result_from_report(data: dict[str, Any]) -> ScanResult:
    """
    Convert a ScanReport, as written by ``lcc scan --format json``, to a ScanResult.

    A finding carries its resolved license but no status, so the status follows
    the console reporter: a resolved license on a component that is not marked
    AI-license-restricted is PASS, anything else is WARNING.
    """
    components = []
    component_results = []
    for finding in data.get("findings", []):
        component = _deserialize_component(finding["component"])
        resolved = finding.get("resolved_license")
        licenses = []
        if resolved:
            licenses.append(
                LicenseEvidence(
                    source="lcc",
                    license_expression=resolved,
                    confidence=float(finding.get("confidence") or 0.0),
                )
            )
        restricted = bool(component.metadata.get("ai_license_restricted"))
        components.append(component)
        component_results.append(
            ComponentResult(
                component=component,
                status=Status.PASS if resolved and not restricted else Status.WARNING,
                licenses=licenses,
            )
        )

    generated_at = (data.get("summary") or {}).get("generated_at")
    return ScanResult(
        components=components,
        component_results=component_results,
        scan_id=data.get("scan_id", "unknown"),
        timestamp=datetime.fromisoformat(generated_at) if generated_at else datetime.now(),
    )


def deserialize_scan_result(data: dict[str, Any]) -> ScanResult:
    """
    Deserialize a ScanResult from JSON data.

    Accepts the ScanReport written by ``lcc scan --format json`` (``findings``
    and ``summary``) and the ScanResult shape (``components`` and
    ``component_results``).

    Args:
        data: Dictionary from JSON

    Returns:
        ScanResult object

    Raises:
        ValueError: If the data is neither shape.
    """
    if "findings" in data:
        return _scan_result_from_report(data)
    if "components" not in data:
        raise ValueError(
            "Not an LCC scan result: expected 'findings' (from `lcc scan --format json`) "
            "or 'components'."
        )

    # Deserialize components
    components = [_deserialize_component(comp_data) for comp_data in data.get("components", [])]

    # Deserialize component results
    component_results = []
    for cr_data in data.get("component_results", []):
        # Find matching component
        component = next(
            (
                c
                for c in components
                if c.name == cr_data["component"]["name"]
                and c.version == cr_data["component"]["version"]
            ),
            None,
        )

        if not component:
            continue

        # Deserialize license evidence
        licenses = []
        for lic_data in cr_data.get("licenses", []):
            lic = LicenseEvidence(
                source=lic_data["source"],
                license_expression=lic_data["license_expression"],
                confidence=lic_data["confidence"],
                raw_data=lic_data.get("raw_data", {}),
            )
            licenses.append(lic)

        cr = ComponentResult(
            component=component,
            status=Status(cr_data["status"]),
            licenses=licenses,
            violations=cr_data.get("violations", []),
            warnings=cr_data.get("warnings", []),
        )
        component_results.append(cr)

    # Create ScanResult
    scan_result = ScanResult(
        components=components,
        component_results=component_results,
        scan_id=data.get("scan_id", "unknown"),
        timestamp=datetime.fromisoformat(data["timestamp"])
        if "timestamp" in data
        else datetime.now(),
    )

    return scan_result

