"""A model referenced by Hub ID never takes the scanned project's license."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError

import lcc.resolution.hf_hub_resolver as hf_hub_resolver
from lcc.config import LCCConfig
from lcc.detection.huggingface import HuggingFaceReferenceDetector
from lcc.models import Component, ComponentFinding, ComponentType
from lcc.resolution.ai_model import AIModelLicenseResolver
from lcc.resolution.fallback import FallbackResolver
from lcc.resolution.filesystem import FileSystemResolver

MODEL_ID = "meta-llama/Llama-3-8B-Instruct"


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "proj"
    project.mkdir()
    (project / "app.py").write_text(
        f'model = AutoModel.from_pretrained("{MODEL_ID}")\n', encoding="utf-8"
    )
    (project / "LICENSE").write_text("SPDX-License-Identifier: MIT\n", encoding="utf-8")
    return project


def _resolve(project: Path, offline: bool = False) -> ComponentFinding:
    detector = HuggingFaceReferenceDetector()
    detector.set_config(SimpleNamespace(offline=offline, exclude_patterns=[]))
    components = detector.discover(project)
    assert [f"{c.namespace}/{c.name}" for c in components] == [MODEL_ID]

    finding = ComponentFinding(component=components[0])
    FallbackResolver([AIModelLicenseResolver(), FileSystemResolver(LCCConfig())]).resolve(finding)
    return finding


def test_hub_401_resolves_to_unknown(tmp_path, monkeypatch):
    def _unauthorized(request, timeout=None):
        raise HTTPError(request.full_url, 401, "Unauthorized", None, None)

    monkeypatch.setattr(hf_hub_resolver, "urlopen", _unauthorized)
    monkeypatch.setattr(hf_hub_resolver, "HF_CACHE", {})

    finding = _resolve(_project(tmp_path))

    assert finding.component.metadata["hub_api_available"] is False
    assert finding.evidences == []
    assert finding.resolved_license is None
    assert finding.confidence == 0.0


def test_offline_reference_resolves_to_unknown(tmp_path):
    finding = _resolve(_project(tmp_path), offline=True)

    assert finding.evidences == []
    assert finding.resolved_license is None


def test_card_license_is_still_used(tmp_path, monkeypatch):
    info = hf_hub_resolver.HFModelInfo(
        model_id=MODEL_ID,
        license="llama3",
        datasets=[],
        tags=[],
        pipeline_tag=None,
        use_restrictions=[],
        card_data={},
    )
    monkeypatch.setattr(hf_hub_resolver, "fetch_model_info", lambda model_id, hf_token=None: info)

    finding = _resolve(_project(tmp_path))

    assert [e.source for e in finding.evidences] == ["ai-model-card"]
    assert finding.resolved_license != "MIT"


def test_local_component_still_reads_license_files(tmp_path):
    project = _project(tmp_path)
    component = Component(
        type=ComponentType.GENERIC, name="LICENSE", version="*", path=project / "LICENSE"
    )

    evidences = list(FileSystemResolver(LCCConfig()).resolve(component))

    assert [e.license_expression for e in evidences] == ["MIT"]
