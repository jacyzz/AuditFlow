from ipaddress import ip_network
from pathlib import Path
from typing import Annotated, Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

Seconds = Annotated[int, Field(ge=1, le=86400)]
StageName = Literal[
    "scout", "triage_project", "surface_map", "deep_audit", "triage_vuln", "verify",
    "evidence", "report",
]


class UniqueKeyLoader(yaml.SafeLoader):
    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict:
        self.flatten_mapping(node)
        result = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str):
                raise ValueError("YAML mapping keys must be strings")
            if key in result:
                raise ValueError(f"duplicate YAML key: {key}")
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def read_yaml(path: Path) -> dict:
    try:
        data = yaml.load(path.read_text(encoding="utf-8"), Loader=UniqueKeyLoader)
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid YAML in {path.name}: {exc.problem}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} must contain a YAML mapping")
    return data


class ConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class Gates(ConfigModel):
    gate1_after_scout: bool = True
    gate2_after_audit: bool = True
    pause_on_env_blocker: bool = True


class Stage(ConfigModel):
    skill: str | None = None
    skills: list[str] = Field(default_factory=list)
    adapter: str | None = None
    backend: str = "local"
    timeout_sec: Seconds = 300
    max_env_retries: Annotated[int, Field(ge=0, le=20)] | None = None
    renderers: list[Literal["code", "web", "http", "term"]] = Field(default_factory=list)

    @property
    def skill_names(self) -> list[str]:
        return [self.skill] if self.skill else self.skills

    @model_validator(mode="after")
    def check_binding(self) -> Self:
        if bool(self.skill_names) == bool(self.renderers) or self.skill and self.skills:
            raise ValueError("choose one of skill, skills, or renderers")
        if bool(self.skill_names) != bool(self.adapter):
            raise ValueError("an adapter must accompany a skill binding")
        return self


class Pipeline(ConfigModel):
    pipeline_name: str
    gates: Gates = Field(default_factory=Gates)
    stages: dict[StageName, Stage]
    adapters: dict[str, dict] = Field(default_factory=dict)
    custom_adapters: dict[str, dict] = Field(default_factory=dict)

    @model_validator(mode="after")
    def nonempty_stages(self) -> Self:
        if not self.stages:
            raise ValueError("configure at least one stage")
        if self.adapters.keys() & self.custom_adapters.keys():
            raise ValueError("adapter names must be unique")
        return self


class ExcelSettings(ConfigModel):
    enabled: bool = False
    excel_path: str = ""

    @model_validator(mode="after")
    def required_when_enabled(self) -> Self:
        if self.enabled and not self.excel_path:
            raise ValueError("excel_path is required when Excel sync is enabled")
        return self


class Paths(ConfigModel):
    windows_report_output_dir: Path = Path("output")
    local_cache_dir: Path = Path(".auditflow_cache")
    tracker_db_path: Path = Path(".auditflow_cache/tracker.sqlite")
    excel_sync: ExcelSettings = Field(default_factory=ExcelSettings)


class SshSettings(ConfigModel):
    host: str
    workspace_root: str
    connect_timeout_sec: Seconds = 15


class WslSettings(ConfigModel):
    distro: str
    workspace_root: str


class Backends(ConfigModel):
    ssh_ubuntu: SshSettings | None = Field(default=None, alias="ssh-ubuntu")
    wsl2: WslSettings | None = None


class DockerSettings(ConfigModel):
    http_proxy: str = ""
    https_proxy: str = ""
    no_proxy: str = "localhost,127.0.0.1,::1"
    port_range: tuple[int, int] = (18000, 19999)
    enforce_port_range: bool = True
    startup_timeout_sec: Seconds = 300
    max_retries: Annotated[int, Field(ge=0, le=20)] = 2
    allowed_target_hosts: list[str] = Field(default_factory=lambda: ["localhost"])
    allowed_target_cidrs: list[str] = Field(default_factory=lambda: ["127.0.0.0/8", "::1/128"])
    burp_upstream_proxy: str | None = None

    @model_validator(mode="after")
    def validate_network_settings(self) -> Self:
        first, last = self.port_range
        if not 1024 <= first <= last <= 65535:
            raise ValueError("expected an ordered port range between 1024 and 65535")
        for entry in self.allowed_target_cidrs:
            ip_network(entry)
        return self


class Platforms(ConfigModel):
    github_token_env: str = "GITHUB_TOKEN"
    gitee_token_env: str = "GITEE_TOKEN"
    gitcode_token_env: str = "GITCODE_TOKEN"


class Env(ConfigModel):
    paths: Paths = Field(default_factory=Paths)
    backends: Backends = Field(default_factory=Backends)
    docker_verify: DockerSettings = Field(default_factory=DockerSettings)
    platforms: Platforms = Field(default_factory=Platforms)


def load_pipeline(path: Path) -> Pipeline:
    return Pipeline.model_validate(read_yaml(path))


def load_env(path: Path | None = None) -> Env:
    return Env.model_validate(read_yaml(path)) if path is not None else Env()
