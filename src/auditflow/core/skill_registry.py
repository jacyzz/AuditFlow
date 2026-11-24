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


class SkillRegistry:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def get(self, name: str) -> Skill:
        if relative_path(name).count("/") != 1:
            raise ValueError("skill names must use category/name")
        directory = contained_path(self.root, name)
        manifest = Skill.model_validate(read_yaml(contained_path(directory, "skill.yaml")))
        if manifest.name != name:
            raise ValueError(f"skill manifest name does not match its directory: {name}")
        manifest._directory = directory
        if not manifest.prompt_path.is_file():
            raise FileNotFoundError(f"SKILL.md missing for {name}")
        for value in manifest.inputs + manifest.outputs:
            relative_path(value)
        return manifest

    def list(self) -> list[str]:
        return [
            path.parent.relative_to(self.root).as_posix()
            for path in sorted(self.root.glob("*/*/skill.yaml"))
        ]
