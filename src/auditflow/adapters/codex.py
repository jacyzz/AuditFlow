from pathlib import Path

from auditflow.adapters.base import AdapterRequest, CliAgentAdapter


class CodexAdapter(CliAgentAdapter):
    """Execute Codex CLI (`codex exec ...`) on the configured execution backend."""

    binary = "codex"
    default_args = ("exec", "--full-auto")

    def build_argv(self, req: AdapterRequest, prompt_file: Path, prompt_text: str) -> list[str]:
        return [self._binary(), *self._extra_args(), prompt_text]
