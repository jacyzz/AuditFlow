import re
import shutil
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from auditflow.core.config import read_yaml
from auditflow.core.paths import atomic_write, contained_path
from auditflow.core.skill_registry import SkillManifest, SkillRegistry

_STAGE_FOLDER = {
    "dispatcher": "dispatcher",
    "scout": "scout",
    "triage_project": "triage",
    "triage_vuln": "triage",
    "surface_map": "audit",
    "deep_audit": "audit",
    "verify": "verify",
    "report": "report",
}
_VALID_SLUG = re.compile(r"^[a-z0-9][a-z0-9_-]{1,60}$")


class SkillRecord(BaseModel):
    name: str
    stage: str
    version: str
    description: str
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    recommended_adapter: str | None = None
    target_categories: list[str] = Field(default_factory=list)
    source: str  # "builtin" | "custom" | "override"
    editable: bool = True
    can_reset: bool = False
    can_delete: bool = False
    prompt_markdown: str = ""
    manifest_yaml: str = ""


class SkillManager:
    """Manage built-in skills + user overlay skills (`skills_custom/`, priority custom > builtin)."""

    def __init__(self, builtin_dir: Path, custom_dir: Path | None = None) -> None:
        self.builtin_dir = builtin_dir.resolve()
        self.custom_dir = (
            custom_dir.resolve()
            if custom_dir is not None
            else (self.builtin_dir.parent / "skills_custom").resolve()
        )

    def _scan_dir(self, root: Path) -> dict[str, SkillManifest]:
        if not root.is_dir():
            return {}
        reg = SkillRegistry(root, include_custom=False)
        return {name: reg.get(name) for name in reg.list()}

    def merged_registry(self) -> dict[str, tuple[SkillManifest, str]]:
        builtins = self._scan_dir(self.builtin_dir)
        customs = self._scan_dir(self.custom_dir)
        merged: dict[str, tuple[SkillManifest, str]] = {}
        for name, m in builtins.items():
            if name in customs:
                merged[name] = (customs[name], "override")
            else:
                merged[name] = (m, "builtin")
        for name, m in customs.items():
            if name not in merged:
                merged[name] = (m, "custom")
        return merged

    def list_skills(self) -> list[SkillRecord]:
        records: list[SkillRecord] = []
        for name, (manifest, source) in sorted(self.merged_registry().items()):
            records.append(self._to_record(manifest, source, include_body=False))
        return records

    def get_skill(self, name: str) -> SkillRecord:
        merged = self.merged_registry()
        if name not in merged:
            raise ValueError(f"unknown skill: {name}")
        manifest, source = merged[name]
        return self._to_record(manifest, source, include_body=True)

    def _to_record(self, manifest: SkillManifest, source: str, *, include_body: bool) -> SkillRecord:
        skill_yaml_path = manifest.prompt_path.parent / "skill.yaml"
        return SkillRecord(
            name=manifest.name,
            stage=manifest.stage,
            version=manifest.version,
            description=manifest.description,
            inputs=manifest.inputs,
            outputs=manifest.outputs,
            recommended_adapter=manifest.recommended_adapter,
            target_categories=manifest.target_categories,
            source=source,
            editable=True,
            can_reset=(source == "override"),
            can_delete=(source == "custom"),
            prompt_markdown=manifest.prompt_path.read_text(encoding="utf-8") if include_body else "",
            manifest_yaml=skill_yaml_path.read_text(encoding="utf-8") if include_body and skill_yaml_path.is_file() else "",
        )

    def _target_folder_for(self, name: str, stage: str) -> Path:
        parts = name.split("/")
        if len(parts) != 2 or not _VALID_SLUG.fullmatch(parts[0]) or not _VALID_SLUG.fullmatch(parts[1]):
            raise ValueError("skill name must be `<group>/<slug>` using lowercase letters, digits, - or _")
        group, slug = parts
        if stage not in _STAGE_FOLDER:
            raise ValueError(f"unsupported stage: {stage}")
        return contained_path(self.custom_dir, f"{group}/{slug}")

    def save_skill(self, name: str, *, manifest_yaml: str, prompt_markdown: str) -> SkillRecord:
        """Save edits to a skill into `skills_custom/` (never destroys built-in source)."""
        parsed = yaml.safe_load(manifest_yaml)
        if not isinstance(parsed, dict):
            raise ValueError("skill.yaml must be a YAML mapping")
        if parsed.get("name") != name:
            raise ValueError(f"skill.yaml name must stay {name!r}")
        validated = SkillManifest.model_validate(parsed)
        folder = self._target_folder_for(validated.name, validated.stage)
        atomic_write(folder / "skill.yaml", manifest_yaml.strip().encode("utf-8") + b"\n")
        atomic_write(folder / "SKILL.md", prompt_markdown.strip().encode("utf-8") + b"\n")
        return self.get_skill(name)

    def create_skill(
        self,
        *,
        name: str,
        stage: str,
        description: str,
        prompt_markdown: str,
        inputs: list[str] | None = None,
        outputs: list[str] | None = None,
        recommended_adapter: str | None = None,
        target_categories: list[str] | None = None,
    ) -> SkillRecord:
        if name in self.merged_registry():
            raise ValueError(f"skill already exists: {name}")
        default_outputs = {
            "dispatcher": ["audit-disposition.json"],
            "scout": ["meta.json"],
            "triage_project": ["meta.json"],
            "surface_map": ["surface.json"],
            "deep_audit": ["audit-disposition.json"],
            "triage_vuln": ["audit-disposition.json"],
            "verify": ["verify.json"],
            "report": ["cnvd-form.json"],
        }
        manifest_data: dict[str, Any] = {
            "name": name,
            "stage": stage,
            "version": "1.0.0",
            "description": description,
            "inputs": inputs or [],
            "outputs": outputs or default_outputs.get(stage, ["meta.json"]),
        }
        if recommended_adapter:
            manifest_data["recommended_adapter"] = recommended_adapter
        if target_categories:
            manifest_data["target_categories"] = target_categories
        validated = SkillManifest.model_validate(manifest_data)
        folder = self._target_folder_for(validated.name, validated.stage)
        manifest_yaml = yaml.safe_dump(manifest_data, allow_unicode=True, sort_keys=False)
        atomic_write(folder / "skill.yaml", manifest_yaml.encode("utf-8"))
        atomic_write(folder / "SKILL.md", prompt_markdown.strip().encode("utf-8") + b"\n")
        return self.get_skill(name)

    def fork_skill(self, source_name: str, new_name: str) -> SkillRecord:
        src = self.get_skill(source_name)
        parsed = read_yaml(self.merged_registry()[source_name][0].prompt_path.parent / "skill.yaml")
        parsed["name"] = new_name
        parsed["description"] = f"{parsed.get('description', '')}（自定义副本）".strip()
        manifest_yaml = yaml.safe_dump(parsed, allow_unicode=True, sort_keys=False)
        return self.save_skill(new_name, manifest_yaml=manifest_yaml, prompt_markdown=src.prompt_markdown)

    def reset_or_delete_skill(self, name: str) -> str:
        merged = self.merged_registry()
        if name not in merged:
            raise ValueError(f"unknown skill: {name}")
        manifest, source = merged[name]
        if source == "builtin":
            raise ValueError("built-in skill cannot be deleted; edit or fork it instead")
        folder = manifest.prompt_path.parent
        if not folder.resolve().is_relative_to(self.custom_dir):
            raise ValueError("refusing to delete outside skills_custom/")
        shutil.rmtree(folder)
        return "reset_to_builtin" if source == "override" else "deleted"
