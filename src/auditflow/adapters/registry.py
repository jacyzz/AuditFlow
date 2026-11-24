from importlib.metadata import entry_points
from typing import Callable

from auditflow.adapters.base import BaseAgentAdapter
from auditflow.adapters.claude_code import ClaudeCodeAdapter
from auditflow.adapters.codex import CodexAdapter
from auditflow.adapters.custom_cli import CustomCLIAdapter
from auditflow.adapters.dsh import DshAdapter
from auditflow.adapters.native_subagent import NativeSubagentAdapter
from auditflow.adapters.openai_api import OpenAIAPIAdapter

Factory = Callable[[str, dict], BaseAgentAdapter]


class AdapterRegistry:
    def __init__(self, options: dict[str, dict] | None = None) -> None:
        self.options = options or {}
        self.factories: dict[str, Factory] = {
            "openai-api": OpenAIAPIAdapter,
            "dsh": DshAdapter,
            "codex": CodexAdapter,
            "claude-code": ClaudeCodeAdapter,
            "native-subagent": NativeSubagentAdapter,
            "custom-cli": CustomCLIAdapter,
        }

    def register(self, name: str, factory: Factory) -> None:
        if name in self.factories:
            raise ValueError(f"adapter is already registered: {name}")
        self.factories[name] = factory

    def get(self, name: str) -> BaseAgentAdapter:
        options = self.options.get(name, {})
        factory = self.factories.get(options.get("type", name))
        if factory is None:
            plugins = tuple(entry_points(group="auditflow.adapters", name=name))
            if len(plugins) != 1:
                raise ValueError(f"adapter unavailable or ambiguous: {name}")
            factory = plugins[0].load()
        adapter = factory(name, options)
        if not isinstance(adapter, BaseAgentAdapter):
            raise ValueError(f"adapter must implement BaseAgentAdapter: {name}")
        return adapter
