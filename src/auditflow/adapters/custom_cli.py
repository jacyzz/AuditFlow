import shlex
from pathlib import Path

from auditflow.adapters.base import (
    AdapterRequest,
    AdapterResult,
    CliAgentAdapter,
    HandoffAdapter,
)
from auditflow.backends.base import BaseExecutionBackend


class CustomCLIAdapter(CliAgentAdapter):
    """Execute a user-defined CLI command template safely via argv token substitution.

    Falls back to a structured handoff packet when `command_template` is omitted.
    """

    binary = ""

    def _template(self) -> str | None:
        tpl = self.options.get("command_template")
        if tpl is None:
            return None
        if not isinstance(tpl, str) or not tpl.strip():
            raise ValueError(f"command_template for {self.name} must be a non-empty string")
        return tpl

    def check_health(self) -> tuple[bool, str]:
        tpl = self._template()
        if tpl is None:
            return True, "manual handoff (no command_template configured)"
        tokens = shlex.split(tpl)
        if not tokens:
            return False, "empty command_template"
        self.binary = tokens[0]
        return super().check_health()

    def build_argv(self, req: AdapterRequest, prompt_file: Path, prompt_text: str) -> list[str]:
        tpl = self._template()
        if tpl is None:
            raise ValueError("command_template is required to build argv")
        mapping = {
            "skill_path": str(req.skill_path),
            "workspace_dir": str(req.workspace_dir),
            "output_file": str(req.output_file),
            "stage": req.stage,
            "prompt_file": str(prompt_file),
        }
        tokens = shlex.split(tpl)
        return [token.format_map(mapping) for token in tokens]

    def run(self, req: AdapterRequest, backend: BaseExecutionBackend) -> AdapterResult:
        if self._template() is None:
            return HandoffAdapter(self.name, self.options).run(req, backend)
        return super().run(req, backend)
