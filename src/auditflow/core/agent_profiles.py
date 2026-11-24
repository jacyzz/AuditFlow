import os
import shutil
from pathlib import Path
from typing import Any, Literal

import httpx
import yaml
from pydantic import BaseModel, Field

from auditflow.core.config import Pipeline
from auditflow.core.paths import atomic_write

CapabilityTag = Literal[
    "deep_reasoning",
    "docker_verify",
    "bulk_triage",
    "cn_writing",
    "tool_use",
    "long_context",
]
CostTier = Literal["free", "low", "medium", "high"]
AuthMode = Literal["official_subscription", "official_api", "third_party_provider", "host_session"]


class AgentProfile(BaseModel):
    name: str
    display_name: str
    vendor: str
    kind: Literal["cli", "api", "host", "custom-cli"]
    auth_modes: list[AuthMode] = Field(default_factory=list)
    capabilities: list[CapabilityTag] = Field(default_factory=list)
    capability_scores: dict[str, int] = Field(default_factory=dict)
    cost_tier: CostTier = "medium"
    preferred_backend: Literal["local", "ssh-ubuntu", "wsl2"] = "local"
    recommended_roles: list[str] = Field(default_factory=list)
    description: str = ""
    detected: bool = False
    binary_path: str | None = None
    native_config_path: str | None = None
    native_config_exists: bool = False
    status_detail: str = ""
    enabled: bool = False
    adapter_config: dict[str, Any] = Field(default_factory=dict)


class ApiProvider(BaseModel):
    id: str
    name: str
    preset: str = "custom"
    base_url: str
    api_key_env: str = "AUDITFLOW_OPENAI_API_KEY"
    api_key_inline: str | None = None
    default_model: str
    models: list[str] = Field(default_factory=list)
    is_coordinator_default: bool = False
    enabled: bool = True


PROVIDER_PRESETS: list[dict[str, Any]] = [
    {
        "preset": "deepseek",
        "name": "DeepSeek 官方 API",
        "base_url": "https://api.deepseek.com/v1",
        "api_key_env": "DEEPSEEK_API_KEY",
        "default_model": "deepseek-chat",
        "models": ["deepseek-chat", "deepseek-reasoner"],
    },
    {
        "preset": "openai",
        "name": "OpenAI 官方 API",
        "base_url": "https://api.openai.com/v1",
        "api_key_env": "OPENAI_API_KEY",
        "default_model": "gpt-4.1",
        "models": ["gpt-4.1", "gpt-4.1-mini", "o4-mini"],
    },
    {
        "preset": "dashscope",
        "name": "阿里云百炼 / 通义千问 (Qwen)",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "api_key_env": "DASHSCOPE_API_KEY",
        "default_model": "qwen-max",
        "models": ["qwen-max", "qwen-plus", "qwen-coder-plus"],
    },
    {
        "preset": "openrouter",
        "name": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "api_key_env": "OPENROUTER_API_KEY",
        "default_model": "anthropic/claude-sonnet-4",
        "models": ["anthropic/claude-sonnet-4", "google/gemini-2.5-pro", "deepseek/deepseek-chat"],
    },
    {
        "preset": "ollama",
        "name": "本地 Ollama",
        "base_url": "http://127.0.0.1:11434/v1",
        "api_key_env": "OLLAMA_API_KEY",
        "default_model": "qwen2.5-coder:32b",
        "models": ["qwen2.5-coder:32b", "deepseek-r1:32b"],
    },
]

# Built-in Agent Profile Catalog (Dimo ADR-0022/0064 inspired: read-only native config inspection)
_BUILTIN_CATALOG: list[dict[str, Any]] = [
    {
        "name": "codex",
        "display_name": "OpenAI Codex CLI",
        "vendor": "OpenAI",
        "kind": "cli",
        "binaries": ["codex"],
        "native_paths": ["~/.codex/config.toml", "~/.codex/auth.json"],
        "auth_modes": ["official_subscription", "official_api", "third_party_provider"],
        "capabilities": ["docker_verify", "tool_use", "deep_reasoning"],
        "capability_scores": {
            "deep_reasoning": 88,
            "docker_verify": 96,
            "bulk_triage": 65,
            "cn_writing": 68,
            "tool_use": 95,
            "long_context": 85,
        },
        "cost_tier": "medium",
        "preferred_backend": "ssh-ubuntu",
        "recommended_roles": ["verify", "deep_audit"],
        "description": "工程排错、Docker 容器部署、最小复现脚本与正负向验证极强；适合担任验证工程师，只产出结构化事实 JSON。",
        "default_config": {"binary": "codex", "extra_args": ["exec", "--full-auto"]},
    },
    {
        "name": "claude-code",
        "display_name": "Claude Code CLI",
        "vendor": "Anthropic",
        "kind": "cli",
        "binaries": ["claude"],
        "native_paths": ["~/.claude/settings.json", "~/.claude/.credentials.json"],
        "auth_modes": ["official_subscription", "official_api", "third_party_provider"],
        "capabilities": ["deep_reasoning", "long_context", "cn_writing", "tool_use"],
        "capability_scores": {
            "deep_reasoning": 96,
            "docker_verify": 86,
            "bulk_triage": 60,
            "cn_writing": 95,
            "tool_use": 92,
            "long_context": 96,
        },
        "cost_tier": "high",
        "preferred_backend": "ssh-ubuntu",
        "recommended_roles": ["deep_audit", "triage_vuln", "report"],
        "description": "跨文件复杂调用链追踪、权限边界分析与自然中文技术写作顶尖；适合高价值深审、异构复核与 CNVD 报告定稿。",
        "default_config": {"binary": "claude", "extra_args": ["-p", "--output-format", "json"]},
    },
    {
        "name": "dsh",
        "display_name": "DeepSeek Harness (dsh)",
        "vendor": "DeepSeek",
        "kind": "cli",
        "binaries": ["dsh"],
        "native_paths": ["~/.dsh", "~/.config/dsh"],
        "auth_modes": ["official_api", "third_party_provider"],
        "capabilities": ["deep_reasoning", "bulk_triage", "tool_use", "long_context"],
        "capability_scores": {
            "deep_reasoning": 90,
            "docker_verify": 80,
            "bulk_triage": 92,
            "cn_writing": 88,
            "tool_use": 88,
            "long_context": 88,
        },
        "cost_tier": "low",
        "preferred_backend": "ssh-ubuntu",
        "recommended_roles": ["surface_map", "deep_audit"],
        "description": "开源插件化 Agent Runtime，自带可回放轨迹日志，挂接高性价比模型做大仓库安全面测绘与第一轮深审性价比极高。",
        "default_config": {"binary": "dsh", "extra_args": ["--non-interactive"]},
    },
    {
        "name": "antigravity-cli",
        "display_name": "Antigravity CLI (agy)",
        "vendor": "Google DeepMind",
        "kind": "custom-cli",
        "binaries": ["agy", "antigravity"],
        "native_paths": ["~/.gemini/antigravity-cli", "~/.gemini/antigravity"],
        "auth_modes": ["official_subscription"],
        "capabilities": ["deep_reasoning", "cn_writing", "tool_use", "long_context"],
        "capability_scores": {
            "deep_reasoning": 94,
            "docker_verify": 84,
            "bulk_triage": 75,
            "cn_writing": 96,
            "tool_use": 92,
            "long_context": 96,
        },
        "cost_tier": "medium",
        "preferred_backend": "local",
        "recommended_roles": ["triage_vuln", "report", "deep_audit"],
        "description": "强综合推理、长上下文与自然流畅中文技术报告写作；极适合担任异构复核与 Windows 侧 CNVD 终稿主笔。",
        "default_config": {
            "type": "custom-cli",
            "command_template": "agy --skill {skill_path} --workspace {workspace_dir} --out {output_file}",
        },
    },
    {
        "name": "gemini-cli",
        "display_name": "Gemini CLI",
        "vendor": "Google",
        "kind": "custom-cli",
        "binaries": ["gemini"],
        "native_paths": ["~/.gemini/settings.json"],
        "auth_modes": ["official_subscription", "official_api"],
        "capabilities": ["long_context", "deep_reasoning", "cn_writing"],
        "capability_scores": {
            "deep_reasoning": 88,
            "docker_verify": 75,
            "bulk_triage": 85,
            "cn_writing": 90,
            "tool_use": 82,
            "long_context": 98,
        },
        "cost_tier": "low",
        "preferred_backend": "local",
        "recommended_roles": ["surface_map", "triage_vuln", "report"],
        "description": "超大上下文窗口适合一次性读透大型单仓库架构与跨文件数据流。",
        "default_config": {
            "type": "custom-cli",
            "command_template": "gemini -p @{prompt_file}",
        },
    },
    {
        "name": "opencode",
        "display_name": "OpenCode CLI",
        "vendor": "OpenCode",
        "kind": "custom-cli",
        "binaries": ["opencode"],
        "native_paths": ["~/.config/opencode/opencode.json", "~/.local/share/opencode"],
        "auth_modes": ["official_api", "third_party_provider"],
        "capabilities": ["tool_use", "deep_reasoning", "docker_verify"],
        "capability_scores": {
            "deep_reasoning": 86,
            "docker_verify": 84,
            "bulk_triage": 80,
            "cn_writing": 80,
            "tool_use": 88,
            "long_context": 86,
        },
        "cost_tier": "low",
        "preferred_backend": "ssh-ubuntu",
        "recommended_roles": ["surface_map", "deep_audit", "verify"],
        "description": "开源多模型终端编码 Agent，支持接入任意 OpenAI/Anthropic 兼容供应商。",
        "default_config": {
            "type": "custom-cli",
            "command_template": "opencode run --file {prompt_file}",
        },
    },
    {
        "name": "openai-api",
        "display_name": "OpenAI 兼容 API（DeepSeek / Qwen / OpenAI）",
        "vendor": "Multi-Provider",
        "kind": "api",
        "env_keys": [
            "AUDITFLOW_OPENAI_API_KEY",
            "DEEPSEEK_API_KEY",
            "OPENAI_API_KEY",
            "DASHSCOPE_API_KEY",
            "OPENROUTER_API_KEY",
        ],
        "auth_modes": ["official_api", "third_party_provider"],
        "capabilities": ["bulk_triage", "cn_writing"],
        "capability_scores": {
            "deep_reasoning": 80,
            "docker_verify": 20,
            "bulk_triage": 98,
            "cn_writing": 88,
            "tool_use": 70,
            "long_context": 82,
        },
        "cost_tier": "low",
        "preferred_backend": "local",
        "recommended_roles": ["scout", "triage_project", "report"],
        "description": "直连高吞吐 API，适合大批量项目初筛打分、元数据补全与驱动 Coordinator 对话大脑。",
        "default_config": {
            "base_url_env": "AUDITFLOW_OPENAI_BASE_URL",
            "api_key_env": "AUDITFLOW_OPENAI_API_KEY",
            "model": "deepseek-chat",
        },
    },
    {
        "name": "native-subagent",
        "display_name": "宿主对话委派（当前主会话接管）",
        "vendor": "Host Session",
        "kind": "host",
        "auth_modes": ["host_session"],
        "capabilities": ["deep_reasoning", "cn_writing", "long_context"],
        "capability_scores": {
            "deep_reasoning": 90,
            "docker_verify": 60,
            "bulk_triage": 70,
            "cn_writing": 94,
            "tool_use": 80,
            "long_context": 92,
        },
        "cost_tier": "free",
        "preferred_backend": "local",
        "recommended_roles": ["triage_vuln", "report"],
        "description": "不调用外部 CLI，直接生成结构化任务包由当前对话宿主（如 Antigravity / Claude）处理。",
        "default_config": {},
    },
]

STAGE_ROLE_REQUIREMENTS: dict[str, dict[str, Any]] = {
    "scout": {"role": "侦察员", "primary_cap": "bulk_triage", "secondary_cap": "tool_use"},
    "triage_project": {"role": "项目预审官", "primary_cap": "bulk_triage", "secondary_cap": "deep_reasoning"},
    "surface_map": {"role": "测绘工程师", "primary_cap": "long_context", "secondary_cap": "tool_use"},
    "deep_audit": {"role": "主审研究员", "primary_cap": "deep_reasoning", "secondary_cap": "long_context"},
    "triage_vuln": {
        "role": "异构复核官",
        "primary_cap": "deep_reasoning",
        "secondary_cap": "cn_writing",
        "heterogeneous_from": "deep_audit",
    },
    "verify": {"role": "验证工程师", "primary_cap": "docker_verify", "secondary_cap": "tool_use"},
    "report": {"role": "CNVD 报告主笔", "primary_cap": "cn_writing", "secondary_cap": "deep_reasoning"},
}


def load_providers(path: Path) -> list[ApiProvider]:
    if not path.is_file():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return []
    items = raw.get("providers", [])
    return [ApiProvider.model_validate(item) for item in items if isinstance(item, dict)]


def save_providers(path: Path, providers: list[ApiProvider]) -> None:
    payload = {"providers": [p.model_dump(mode="json") for p in providers]}
    text = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)
    atomic_write(path, text.encode("utf-8"))


def resolve_provider_credentials(provider: ApiProvider) -> tuple[str, str, str]:
    api_key = provider.api_key_inline or os.environ.get(provider.api_key_env, "")
    return provider.base_url.rstrip("/"), api_key, provider.default_model


def test_provider_connection(provider: ApiProvider, *, client: httpx.Client | None = None) -> tuple[bool, str]:
    base_url, api_key, model = resolve_provider_credentials(provider)
    if not api_key and provider.preset != "ollama":
        return False, f"未检测到密钥（请填写 Key 或设置环境变量 {provider.api_key_env}）"
    headers = {"Authorization": f"Bearer {api_key or 'ollama'}"}
    try:
        if client is not None:
            resp = client.get(f"{base_url}/models", headers=headers, timeout=10)
        else:
            with httpx.Client(timeout=10) as conn:
                resp = conn.get(f"{base_url}/models", headers=headers)
        if resp.is_success:
            return True, f"连接正常（HTTP {resp.status_code}，默认模型 {model}）"
        return False, f"端点返回 HTTP {resp.status_code}: {resp.text[:160]}"
    except httpx.HTTPError as exc:
        return False, f"连接失败: {exc}"


def load_profile_overrides(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else {}


def save_profile_overrides(path: Path, overrides: dict[str, dict[str, Any]]) -> None:
    atomic_write(path, yaml.safe_dump(overrides, allow_unicode=True, sort_keys=False).encode("utf-8"))


def discover_agent_profiles(
    pipeline: Pipeline,
    *,
    overrides_path: Path | None = None,
    providers_path: Path | None = None,
) -> list[AgentProfile]:
    """Scan local PATH, read-only native config locations, and configured providers."""
    configured = pipeline.adapters | pipeline.custom_adapters
    used_in_stages = {s.adapter for s in pipeline.stages.values() if s.adapter}
    overrides = load_profile_overrides(overrides_path) if overrides_path else {}
    providers = load_providers(providers_path) if providers_path else []
    profiles: list[AgentProfile] = []
    seen: set[str] = set()

    for spec in _BUILTIN_CATALOG:
        name = spec["name"]
        seen.add(name)
        cfg = dict(configured.get(name, spec["default_config"]))
        ov = overrides.get(name, {})

        detected = False
        binary_path: str | None = None
        native_cfg: str | None = None
        native_exists = False
        detail = ""

        if spec["kind"] in {"cli", "custom-cli"}:
            bins = ([cfg["binary"]] if isinstance(cfg.get("binary"), str) else []) + list(
                spec.get("binaries", [])
            )
            for b in bins:
                found = shutil.which(b)
                if found:
                    detected = True
                    binary_path = found
                    break
            for np in spec.get("native_paths", []):
                expanded = Path(np).expanduser()
                if expanded.exists():
                    native_cfg = str(expanded)
                    native_exists = True
                    break
            if detected and native_exists:
                detail = f"已就绪：{binary_path}（原生配置：{native_cfg}）"
            elif detected:
                detail = f"已检测到 CLI：{binary_path}"
            elif native_exists:
                detail = f"检测到原生目录 {native_cfg}，但当前 PATH 未找到 CLI（可能在远端 Ubuntu）"
            else:
                detail = f"本机未检测到 {'/'.join(bins)}（如装在 Ubuntu2404 仍可启用）"
        elif spec["kind"] == "api":
            active_providers = [p for p in providers if p.enabled]
            env_keys = [cfg.get("api_key_env", "AUDITFLOW_OPENAI_API_KEY"), *spec.get("env_keys", [])]
            found_key = next((k for k in env_keys if os.environ.get(k)), None)
            if active_providers:
                detected = True
                detail = f"已配置 {len(active_providers)} 个 API Provider（默认：{active_providers[0].name}）"
            elif found_key:
                detected = True
                cfg["api_key_env"] = found_key
                detail = f"已检测到环境变量 {found_key}"
            else:
                detail = "未检测到 API Key（可在右侧“API Providers”添加 DeepSeek/OpenAI/Qwen）"
        else:
            detected = True
            detail = "始终可用（由当前主对话直接接管）"

        enabled_default = name in configured or name in used_in_stages or (detected and name != "gemini-cli")
        profiles.append(
            AgentProfile(
                name=name,
                display_name=ov.get("display_name", spec["display_name"]),
                vendor=spec["vendor"],
                kind=spec["kind"],
                auth_modes=spec["auth_modes"],
                capabilities=ov.get("capabilities", spec["capabilities"]),
                capability_scores=ov.get("capability_scores", spec["capability_scores"]),
                cost_tier=ov.get("cost_tier", spec["cost_tier"]),
                preferred_backend=ov.get("preferred_backend", spec["preferred_backend"]),
                recommended_roles=ov.get("recommended_roles", spec["recommended_roles"]),
                description=ov.get("description", spec["description"]),
                detected=detected,
                binary_path=binary_path,
                native_config_path=native_cfg,
                native_config_exists=native_exists,
                status_detail=detail,
                enabled=bool(ov.get("enabled", enabled_default)),
                adapter_config=ov.get("adapter_config", cfg),
            )
        )

    for name, cfg in configured.items():
        if name in seen:
            continue
        ov = overrides.get(name, {})
        cmd = str(cfg.get("command_template") or cfg.get("binary") or "")
        first = cmd.split()[0] if cmd.strip() else ""
        found = shutil.which(first) if first else None
        profiles.append(
            AgentProfile(
                name=name,
                display_name=ov.get("display_name", f"自定义 Agent ({name})"),
                vendor="Custom",
                kind="custom-cli",
                auth_modes=["third_party_provider"],
                capabilities=ov.get("capabilities", ["tool_use", "deep_reasoning"]),
                capability_scores=ov.get(
                    "capability_scores",
                    {"deep_reasoning": 80, "docker_verify": 80, "bulk_triage": 75, "cn_writing": 75, "tool_use": 85, "long_context": 80},
                ),
                cost_tier=ov.get("cost_tier", "medium"),
                preferred_backend=ov.get("preferred_backend", "local"),
                recommended_roles=ov.get("recommended_roles", ["deep_audit"]),
                description=ov.get("description", f"自定义 CLI：{cmd}"),
                detected=bool(found),
                binary_path=found,
                status_detail=found or f"自定义命令：{cmd or '未配置'}",
                enabled=bool(ov.get("enabled", True)),
                adapter_config=ov.get("adapter_config", cfg),
            )
        )
    return profiles


def recommend_stage_assignments(profiles: list[AgentProfile]) -> dict[str, dict[str, Any]]:
    """Recommend optimal Agent per stage based on capability scores + heterogeneous cross-review."""
    pool = [p for p in profiles if p.enabled] or profiles
    assigned: dict[str, dict[str, Any]] = {}
    chosen_map: dict[str, str] = {}

    for stage in ("scout", "triage_project", "surface_map", "deep_audit", "triage_vuln", "verify", "report"):
        req = STAGE_ROLE_REQUIREMENTS[stage]
        primary = req["primary_cap"]
        secondary = req["secondary_cap"]
        avoid_stage = req.get("heterogeneous_from")
        avoid_agent = chosen_map.get(avoid_stage) if avoid_stage else None

        def _score(agent: AgentProfile) -> tuple[int, int, int]:
            s1 = agent.capability_scores.get(primary, 50)
            s2 = agent.capability_scores.get(secondary, 50)
            hetero_bonus = 25 if (avoid_agent and agent.name != avoid_agent) else 0
            detected_bonus = 10 if agent.detected else 0
            role_bonus = 8 if stage in agent.recommended_roles else 0
            total = s1 * 2 + s2 + hetero_bonus + detected_bonus + role_bonus
            return (total, 1 if agent.detected else 0, s1)

        ranked = sorted(pool, key=_score, reverse=True)
        winner = ranked[0]
        chosen_map[stage] = winner.name
        reason = f"岗位「{req['role']}」优先看重 {primary}（{winner.capability_scores.get(primary, 50)}分）"
        if avoid_agent and winner.name != avoid_agent:
            reason += f"，并与主审（{avoid_agent}）保持异构互审防单模型盲区"
        assigned[stage] = {
            "stage": stage,
            "role": req["role"],
            "adapter": winner.name,
            "display_name": winner.display_name,
            "backend": winner.preferred_backend,
            "score": winner.capability_scores.get(primary, 50),
            "heterogeneous_check": bool(avoid_agent and winner.name != avoid_agent),
            "reason": reason,
        }
    return assigned
