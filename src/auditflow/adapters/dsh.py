from pathlib import Path

from auditflow.adapters.base import AdapterRequest, CliAgentAdapter


class DshAdapter(CliAgentAdapter):
    """Execute DeepSeek Harness (`dsh`) CLI on the configured execution backend."""

    binary = "dsh"
    default_args = ("--non-interactive",)

    def build_argv(self, req: AdapterRequest, prompt_file: Path, prompt_text: str) -> list[str]:
        return [self._binary(), *self._extra_args(), prompt_text]
