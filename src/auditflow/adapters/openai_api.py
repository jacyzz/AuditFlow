import json
import os
import time
from uuid import uuid4

import httpx

from auditflow.adapters.base import (
    AdapterRequest,
    AdapterResult,
    BaseAgentAdapter,
    build_stage_prompt,
    extract_json_payload,
)
from auditflow.backends.base import BaseExecutionBackend
from auditflow.core.paths import atomic_write, contained_path


class OpenAIAPIAdapter(BaseAgentAdapter):
    """Direct OpenAI-compatible Chat Completions adapter (DeepSeek / Qwen / OpenAI / Ollama)."""

    def __init__(
        self,
        name: str,
        options: dict | None = None,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        self.name = name
        self.options = options or {}
        self._client = client

    def _base_url(self) -> str:
        env_key = str(self.options.get("base_url_env", "AUDITFLOW_OPENAI_BASE_URL"))
        url = os.environ.get(env_key) or str(self.options.get("base_url", "https://api.openai.com/v1"))
        return url.rstrip("/")

    def _api_key(self) -> str:
        env_key = str(self.options.get("api_key_env", "AUDITFLOW_OPENAI_API_KEY"))
        return os.environ.get(env_key, "")

    def _model(self) -> str:
        return str(self.options.get("model", "deepseek-chat"))

    def check_health(self) -> tuple[bool, str]:
        env_key = str(self.options.get("api_key_env", "AUDITFLOW_OPENAI_API_KEY"))
        if not self._api_key():
            return False, f"environment variable `{env_key}` is not set"
        return True, f"OpenAI-compatible API ready (model={self._model()}, base={self._base_url()})"

    def run(self, req: AdapterRequest, backend: BaseExecutionBackend) -> AdapterResult:
        started = time.monotonic()
        api_key = self._api_key()
        if not api_key and self._client is None:
            env_key = str(self.options.get("api_key_env", "AUDITFLOW_OPENAI_API_KEY"))
            return AdapterResult(
                ok=False,
                adapter_name=self.name,
                model_used=self._model(),
                error_message=f"missing API key in environment variable `{env_key}`",
            )
        skill_text = req.skill_path.read_text(encoding="utf-8")
        user_prompt = build_stage_prompt(req, inline_inputs=True)
        payload: dict = {
            "model": self._model(),
            "temperature": float(self.options.get("temperature", 0.1)),
            "messages": [
                {"role": "system", "content": skill_text},
                {"role": "user", "content": user_prompt},
            ],
        }
        if self.options.get("json_mode", True):
            payload["response_format"] = {"type": "json_object"}
        endpoint = f"{self._base_url()}/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key or 'test-key'}",
            "Content-Type": "application/json",
        }
        trajectory_path = contained_path(
            req.workspace_dir, f"logs/openai-api-{uuid4().hex}.json"
        )
        try:
            if self._client is not None:
                response = self._client.post(endpoint, headers=headers, json=payload, timeout=req.timeout_sec)
            else:
                with httpx.Client(timeout=req.timeout_sec) as client:
                    response = client.post(endpoint, headers=headers, json=payload)
            duration = round(time.monotonic() - started, 3)
            raw_text = response.text
            atomic_write(
                trajectory_path,
                (
                    json.dumps(
                        {
                            "adapter": self.name,
                            "endpoint": endpoint,
                            "model": self._model(),
                            "status_code": response.status_code,
                            "duration_sec": duration,
                            "response_body": raw_text[:65536],
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                    + "\n"
                ).encode("utf-8"),
            )
            if not response.is_success:
                return AdapterResult(
                    ok=False,
                    adapter_name=self.name,
                    model_used=self._model(),
                    stderr_log=raw_text[:1000],
                    trajectory_path=trajectory_path,
                    duration_sec=duration,
                    error_message=f"API returned HTTP {response.status_code}",
                )
            body = response.json()
            content = body["choices"][0]["message"]["content"]
            if not isinstance(content, str):
                raise ValueError("API response message content is not a string")
            extracted = extract_json_payload(content)
            if extracted is None:
                return AdapterResult(
                    ok=False,
                    adapter_name=self.name,
                    model_used=self._model(),
                    stdout_log=content,
                    trajectory_path=trajectory_path,
                    duration_sec=duration,
                    error_message="API response did not contain a valid JSON object",
                )
            atomic_write(req.output_file, extracted.encode("utf-8"))
            return AdapterResult(
                ok=True,
                adapter_name=self.name,
                model_used=body.get("model", self._model()),
                output_file=req.output_file,
                stdout_log=content,
                trajectory_path=trajectory_path,
                duration_sec=duration,
            )
        except (httpx.HTTPError, KeyError, IndexError, ValueError, TypeError) as exc:
            duration = round(time.monotonic() - started, 3)
            return AdapterResult(
                ok=False,
                adapter_name=self.name,
                model_used=self._model(),
                trajectory_path=trajectory_path if trajectory_path.is_file() else None,
                duration_sec=duration,
                error_message=f"OpenAI API adapter failed: {exc}",
            )
