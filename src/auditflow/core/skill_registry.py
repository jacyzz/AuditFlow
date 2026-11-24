from pathlib import Path
from typing import Annotated

from pydantic import Field, PrivateAttr

from auditflow.core.config import ConfigModel, read_yaml
from auditflow.core.paths import contained_path, relative_path


class Skill(ConfigModel):
    name: str
    stage: str
    version: Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+$")]
    description: str
    target_categories: list[str] = Field(default_factory=list)
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    recommended_adapter: str | None = None
    deterministic_entrypoint: str | None = None
    _directory: Path = PrivateAttr()

    @property
    def prompt_path(self) -> Path:
        return contained_path(self._directory, "SKILL.md")


SkillManifest = Skill


class SkillRegistry:
    def __init__(
        self,
        root: Path,
        custom_root: Path | None = None,
        *,
        include_custom: bool = True,
    ) -> None:
        self.root = root.resolve()
        if not include_custom:
            self.custom_root = None
        elif custom_root is not None:
            self.custom_root = custom_root.resolve()
        else:
            default_custom = (self.root.parent / "skills_custom").resolve()
            self.custom_root = default_custom if default_custom.is_dir() else None

    def _load_from(self, base: Path, name: str) -> Skill:
        directory = contained_path(base, name)
        manifest = Skill.model_validate(read_yaml(contained_path(directory, "skill.yaml")))
        if manifest.name != name:
            raise ValueError(f"skill manifest name does not match its directory: {name}")
        manifest._directory = directory
        if not manifest.prompt_path.is_file():
            raise FileNotFoundError(f"SKILL.md missing for {name}")
        for value in manifest.inputs + manifest.outputs:
            relative_path(value)
        return manifest

    def get(self, name: str) -> Skill:
        if relative_path(name).count("/") != 1:
            raise ValueError("skill names must use category/name")
        if self.custom_root is not None:
            candidate_dir = contained_path(self.custom_root, name)
            if (candidate_dir / "skill.yaml").is_file():
                return self._load_from(self.custom_root, name)
        return self._load_from(self.root, name)

    def list(self) -> list[str]:
        names = {
            path.parent.relative_to(self.root).as_posix()
            for path in self.root.glob("*/*/skill.yaml")
        }
        if self.custom_root is not None and self.custom_root.is_dir():
            names.update(
                path.parent.relative_to(self.custom_root).as_posix()
                for path in self.custom_root.glob("*/*/skill.yaml")
            )
        return sorted(names)
