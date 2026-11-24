from pathlib import Path

from auditflow.adapters.base import AdapterRequest, CliAgentAdapter


class ClaudeCodeAdapter(CliAgentAdapter):
    """Execute Claude Code CLI (`claude -p --output-format json`) on the configured backend."""

    binary = "claude"
    default_args = ("-p", "--output-format", "json")

    def build_argv(self, req: AdapterRequest, prompt_file: Path, prompt_text: str) -> list[str]:
        return [self._binary(), *self._extra_args(), prompt_text]
