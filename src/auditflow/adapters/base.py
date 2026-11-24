import json
import re
import shutil
import time
from abc import ABC, abstractmethod
from pathlib import Path
from uuid import uuid4

from pydantic import Field

from auditflow.backends.base import BaseExecutionBackend
from auditflow.core.config import ConfigModel
from auditflow.core.paths import atomic_write, contained_path
from auditflow.core.schemas import SCHEMAS

_JSON_FENCE = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.DOTALL)


class AdapterRequest(ConfigModel):
    stage: str
    skill_path: Path
    workspace_dir: Path
    input_files: dict[str, Path]
    output_file: Path
    extra_instructions: str = ""
    timeout_sec: int = Field(default=900, gt=0)
    env_vars: dict[str, str] = Field(default_factory=dict, exclude=True)


class AdapterResult(ConfigModel):
    ok: bool
    adapter_name: str
    model_used: str | None = None
    output_file: Path | None = None
    stdout_log: str = ""
    stderr_log: str = ""
    trajectory_path: Path | None = None
    duration_sec: float = Field(default=0, ge=0)
    error_message: str | None = None


class BaseAgentAdapter(ABC):
    name: str

    @abstractmethod
    def check_health(self) -> tuple[bool, str]:
        """Report availability of the adapter."""

    @abstractmethod
    def run(self, req: AdapterRequest, backend: BaseExecutionBackend) -> AdapterResult:
        """Execute a stage using this adapter on the selected backend."""


def extract_json_payload(text: str) -> str | None:
    """Extract a JSON object from raw LLM/CLI output (handles markdown fences and wrappers)."""
    stripped = text.strip()
    if not stripped:
        return None
    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, dict):
            if "result" in parsed and isinstance(parsed["result"], str) and "schema_version" not in parsed:
                nested = extract_json_payload(parsed["result"])
                if nested is not None:
                    return nested
            return json.dumps(parsed, ensure_ascii=False, indent=2) + "\n"
    except json.JSONDecodeError:
        pass
    match = _JSON_FENCE.search(stripped)
    if match:
        candidate = match.group(1)
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return json.dumps(parsed, ensure_ascii=False, indent=2) + "\n"
        except json.JSONDecodeError:
            pass
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end > start:
        candidate = stripped[start : end + 1]
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return json.dumps(parsed, ensure_ascii=False, indent=2) + "\n"
        except json.JSONDecodeError:
            pass
    return None


def build_stage_prompt(req: AdapterRequest, *, inline_inputs: bool = False) -> str:
    skill_text = req.skill_path.read_text(encoding="utf-8")
    schema_model = SCHEMAS.get(req.output_file.name)
    schema_block = (
        json.dumps(schema_model.model_json_schema(), ensure_ascii=False, indent=2)
        if schema_model is not None
        else "{}"
    )
    lines = [
        f"# AuditFlow Stage Task: {req.stage}",
        "",
        "## Skill Instructions",
        skill_text.strip(),
        "",
        "## Execution Context",
        f"- Workspace directory: `{req.workspace_dir}`",
        f"- Required output file: `{req.output_file}`",
        f"- Expected contract: `{req.output_file.name}`",
    ]
    if req.input_files:
        lines.append("- Input artifacts:")
        for key, path in req.input_files.items():
            lines.append(f"  - `{key}`: `{path}`")
    if inline_inputs and req.input_files:
        lines.append("")
        lines.append("## Input Artifact Contents")
        for key, path in req.input_files.items():
            if path.is_file():
                content = path.read_text(encoding="utf-8", errors="replace")[:32000]
                lines.append(f"### {key}")
                lines.append("```json")
                lines.append(content.strip())
                lines.append("```")
    lines.extend(
        [
            "",
            "## Required Output JSON Schema",
            "```json",
            schema_block,
            "```",
            "",
            "## Additional Instructions",
            req.extra_instructions.strip() or "Produce valid JSON matching the schema above.",
            "",
            f"Write the final JSON object directly to `{req.output_file}` (or output ONLY the JSON object).",
        ]
    )
    return "\n".join(lines) + "\n"


class HandoffAdapter(BaseAgentAdapter):
    def __init__(self, name: str, options: dict | None = None) -> None:
        self.name = name
        self.options = options or {}

    def check_health(self) -> tuple[bool, str]:
        return True, "host-managed handoff packet"

    def run(self, req: AdapterRequest, backend: BaseExecutionBackend) -> AdapterResult:
        packet = {
            "adapter": self.name,
            "backend": backend.name,
            "request": req.model_dump(mode="json"),
            "skill": req.skill_path.read_text(encoding="utf-8"),
        }
        path = contained_path(req.workspace_dir, f"logs/handoff-{uuid4().hex}.json")
        atomic_write(path, (json.dumps(packet, ensure_ascii=False, indent=2) + "\n").encode())
        return AdapterResult(
            ok=False,
            adapter_name=self.name,
            trajectory_path=path,
            error_message="Awaiting host subagent or manually reviewed artifact.",
        )


class CliAgentAdapter(BaseAgentAdapter):
    binary: str = ""
    default_args: tuple[str, ...] = ()

    def __init__(self, name: str, options: dict | None = None) -> None:
        self.name = name
        self.options = options or {}

    def _binary(self) -> str:
        return str(self.options.get("binary", self.binary))

    def _extra_args(self) -> list[str]:
        raw = self.options.get("extra_args")
        if raw is None:
            return list(self.default_args)
        if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
            raise ValueError(f"extra_args for adapter {self.name} must be a list of strings")
        return list(raw)

    def build_argv(self, req: AdapterRequest, prompt_file: Path, prompt_text: str) -> list[str]:
        return [self._binary(), *self._extra_args(), prompt_text]

    def check_health(self) -> tuple[bool, str]:
        binary = self._binary()
        resolved = shutil.which(binary)
        if resolved is None:
            return False, f"CLI binary `{binary}` not found in local PATH (may still exist on remote backend)"
        return True, f"CLI ready: {resolved}"

    def run(self, req: AdapterRequest, backend: BaseExecutionBackend) -> AdapterResult:
        started = time.monotonic()
        prompt_text = build_stage_prompt(req, inline_inputs=False)
        prompt_file = contained_path(req.workspace_dir, f"logs/prompt-{req.stage}-{uuid4().hex}.md")
        atomic_write(prompt_file, prompt_text.encode("utf-8"))
        argv = self.build_argv(req, prompt_file, prompt_text)
        cmd_result = backend.run_cmd(
            argv,
            cwd=req.workspace_dir,
            env=req.env_vars or None,
            timeout=req.timeout_sec,
        )
        duration = round(time.monotonic() - started, 3)
        trajectory_path = contained_path(
            req.workspace_dir, f"logs/cli-{self.name}-{uuid4().hex}.json"
        )
        trajectory = {
            "adapter": self.name,
            "backend": backend.name,
            "argv_head": argv[: min(len(argv), 6)],
            "prompt_file": str(prompt_file),
            "returncode": cmd_result.returncode,
            "timed_out": cmd_result.timed_out,
            "duration_sec": duration,
            "stdout": cmd_result.stdout,
            "stderr": cmd_result.stderr,
        }
        atomic_write(trajectory_path, (json.dumps(trajectory, ensure_ascii=False, indent=2) + "\n").encode())
        if not cmd_result.ok:
            reason = (
                f"{self.name} timed out after {req.timeout_sec}s"
                if cmd_result.timed_out
                else f"{self.name} exited with code {cmd_result.returncode}: {cmd_result.stderr.strip()[:400]}"
            )
            return AdapterResult(
                ok=False,
                adapter_name=self.name,
                stdout_log=cmd_result.stdout,
                stderr_log=cmd_result.stderr,
                trajectory_path=trajectory_path,
                duration_sec=duration,
                error_message=reason,
            )
        if not req.output_file.is_file():
            extracted = extract_json_payload(cmd_result.stdout)
            if extracted is not None:
                atomic_write(req.output_file, extracted.encode("utf-8"))
        if not req.output_file.is_file():
            return AdapterResult(
                ok=False,
                adapter_name=self.name,
                stdout_log=cmd_result.stdout,
                stderr_log=cmd_result.stderr,
                trajectory_path=trajectory_path,
                duration_sec=duration,
                error_message=f"{self.name} completed without writing {req.output_file.name}",
            )
        return AdapterResult(
            ok=True,
            adapter_name=self.name,
            model_used=self.options.get("model"),
            output_file=req.output_file,
            stdout_log=cmd_result.stdout,
            stderr_log=cmd_result.stderr,
            trajectory_path=trajectory_path,
            duration_sec=duration,
        )


# Backward-compatible alias
CliHandoff = CliAgentAdapter
