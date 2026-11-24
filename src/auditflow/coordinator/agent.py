import json
import os
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx

from auditflow.coordinator.sessions import ChatStore
from auditflow.core.agent_profiles import (
    discover_agent_profiles,
    load_providers,
    recommend_stage_assignments,
    resolve_provider_credentials,
)
from auditflow.core.config import Env, Pipeline
from auditflow.core.skill_manager import SkillManager
from auditflow.core.state import Tracker
from auditflow.dispatcher.engine import Dispatcher
from auditflow.scout.dedup import save_new_projects
from auditflow.scout.platforms import metadata_from_url, search_projects

_MENTION_RE = re.compile(r"@([a-zA-Z0-9_-]+)")
_URL_RE = re.compile(r"https?://(?:github\.com|gitee\.com|gitcode\.com)/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")

COORDINATOR_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "scout_projects",
            "description": "Search GitHub/Gitee/GitCode repositories by keyword or import explicit repository URLs, deduplicating against SQLite tracker.",
            "parameters": {
                "type": "object",
                "properties": {
                    "platform": {"type": "string", "enum": ["github", "gitee", "gitcode"]},
                    "query": {"type": "string", "description": "Search keywords"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                    "urls": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_pipeline_status",
            "description": "List tracked targets, candidate vulnerabilities, and their current workflow statuses.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recommend_team_assignment",
            "description": "Recommend optimal agent-to-stage assignments based on detected local/remote agent capabilities and heterogeneous cross-review rules.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_pipeline_stage",
            "description": "Run a specific pipeline stage (triage_project, surface_map, deep_audit, triage_vuln, verify, evidence, report) for a target (and optional candidate).",
            "parameters": {
                "type": "object",
                "properties": {
                    "stage": {
                        "type": "string",
                        "enum": [
                            "triage_project",
                            "surface_map",
                            "deep_audit",
                            "triage_vuln",
                            "verify",
                            "evidence",
                            "report",
                        ],
                    },
                    "target": {"type": "string"},
                    "candidate": {"type": "string"},
                },
                "required": ["stage", "target"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_cnvd_report",
            "description": "Generate the final Word .docx report and CNVD submission form for a verified/evidence-ready candidate.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {"type": "string"},
                    "candidate": {"type": "string"},
                },
                "required": ["target", "candidate"],
            },
        },
    },
]


class CoordinatorEngine:
    """Conversational ReAct coordinator that delegates tasks across heterogeneous Agents & Skills."""

    def __init__(
        self,
        *,
        pipeline: Pipeline,
        env: Env,
        workspaces: Path,
        skills_dir: Path,
        providers_path: Path,
        overrides_path: Path,
        chat_store: ChatStore,
        dispatcher: Dispatcher,
    ) -> None:
        self.pipeline = pipeline
        self.env = env
        self.workspaces = workspaces
        self.skill_manager = SkillManager(skills_dir)
        self.providers_path = providers_path
        self.overrides_path = overrides_path
        self.chat_store = chat_store
        self.dispatcher = dispatcher

    def _active_llm(self) -> tuple[str, str, str] | None:
        providers = [p for p in load_providers(self.providers_path) if p.enabled]
        chosen = next((p for p in providers if p.is_coordinator_default), providers[0] if providers else None)
        if chosen is not None:
            base, key, model = resolve_provider_credentials(chosen)
            if key or chosen.preset == "ollama":
                return base, key or "ollama", model
        env_key = os.environ.get("AUDITFLOW_OPENAI_API_KEY") or os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY")
        if env_key:
            base = (
                os.environ.get("AUDITFLOW_OPENAI_BASE_URL")
                or ("https://api.deepseek.com/v1" if os.environ.get("DEEPSEEK_API_KEY") else "https://api.openai.com/v1")
            ).rstrip("/")
            model = os.environ.get("AUDITFLOW_COORDINATOR_MODEL", "deepseek-chat" if "deepseek" in base else "gpt-4.1-mini")
            return base, env_key, model
        return None

    def _exec_tool(self, name: str, args: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
        """Execute a Coordinator tool and optionally return an inline Gate UI card."""
        gate_card: dict[str, Any] | None = None
        if name == "scout_projects":
            tracker = Tracker(self.env.paths.tracker_db_path)
            urls = args.get("urls") or []
            if urls:
                projects = [metadata_from_url(u) for u in urls]
            else:
                platform = str(args.get("platform", "github"))
                query = str(args.get("query", "")).strip()
                limit = int(args.get("limit", 5))
                projects = search_projects(platform, query, self.env.platforms, limit=limit)
            accepted = save_new_projects(projects, tracker, self.workspaces)
            items = [
                {
                    "target_id": p.target_id,
                    "product": p.product,
                    "repo_url": str(p.repo_url),
                    "stars": p.stars,
                    "language": p.primary_language,
                }
                for p in accepted
            ]
            if items:
                for p in accepted:
                    try:
                        tracker.transition_target(p.target_id, "GATE1_PENDING")
                    except ValueError:
                        pass
                gate_card = {
                    "kind": "gate1",
                    "title": f"Gate 1 人工审批：发现 {len(items)} 个新开源目标",
                    "items": items,
                }
            return {"added": len(items), "targets": items}, gate_card

        if name == "list_pipeline_status":
            tracker = Tracker(self.env.paths.tracker_db_path)
            with tracker.connect() as db:
                t_rows = db.execute("SELECT target_id, status FROM targets ORDER BY rowid DESC LIMIT 20").fetchall()
                c_rows = db.execute("SELECT target_id, candidate_id, status FROM candidates ORDER BY rowid DESC LIMIT 30").fetchall()
            return {
                "targets": [{"target_id": r[0], "status": r[1]} for r in t_rows],
                "candidates": [{"target_id": r[0], "candidate_id": r[1], "status": r[2]} for r in c_rows],
            }, None

        if name == "recommend_team_assignment":
            profiles = discover_agent_profiles(
                self.pipeline,
                overrides_path=self.overrides_path,
                providers_path=self.providers_path,
            )
            rec = recommend_stage_assignments(profiles)
            return {
                "detected_agents": [
                    {"name": p.name, "display_name": p.display_name, "detected": p.detected, "enabled": p.enabled}
                    for p in profiles
                ],
                "recommended_assignments": rec,
            }, None

        if name == "run_pipeline_stage":
            stage = str(args["stage"])
            target = str(args["target"])
            candidate = args.get("candidate")
            accepted = self.dispatcher.run_stage(stage, target, str(candidate) if candidate else None)
            result: dict[str, Any] = {"stage": stage, "target": target, "candidate": candidate, "accepted": accepted}
            if stage == "triage_vuln" and accepted:
                tracker = Tracker(self.env.paths.tracker_db_path)
                with tracker.connect() as db:
                    rows = db.execute(
                        "SELECT candidate_id, status FROM candidates WHERE target_id = ?", (target,)
                    ).fetchall()
                gate_card = {
                    "kind": "gate2",
                    "target_id": target,
                    "title": f"Gate 2 人工审批：{target} 候选漏洞",
                    "items": [{"candidate_id": r[0], "status": r[1]} for r in rows],
                }
            return result, gate_card

        if name == "generate_cnvd_report":
            target = str(args["target"])
            candidate = str(args["candidate"])
            paths = self.dispatcher.report(target, candidate, self.env.paths.windows_report_output_dir)
            return {"files": [str(p) for p in paths]}, None

        raise ValueError(f"unknown tool: {name}")

    def handle_message_stream(self, session_id: str, user_text: str) -> Iterator[dict[str, Any]]:
        """Process a user prompt, yielding structured SSE events and persisting messages."""
        self.chat_store.update_title_if_default(session_id, user_text)
        self.chat_store.append_message(session_id, role="user", content=user_text)

        mentions = _MENTION_RE.findall(user_text)
        events: list[dict[str, Any]] = []
        gate_card: dict[str, Any] | None = None

        llm = self._active_llm()
        if llm is not None:
            yield {"type": "status", "message": f"Coordinator ({llm[2]}) 正在规划任务与路由 Agent..."}
            yield from self._run_llm_react(session_id, user_text, mentions, llm)
            return

        # Smart deterministic router when no Coordinator LLM API key is configured yet
        yield {"type": "status", "message": "未检测到 Coordinator API Key，使用内置确定性指令路由..."}
        urls = _URL_RE.findall(user_text)
        reply_parts: list[str] = []

        if urls:
            ev = {"type": "tool_call", "tool": "scout_projects", "args": {"urls": urls}}
            events.append(ev)
            yield ev
            try:
                res, gc = self._exec_tool("scout_projects", {"urls": urls})
                gate_card = gc or gate_card
                ev_r = {"type": "tool_result", "tool": "scout_projects", "result": res}
                events.append(ev_r)
                yield ev_r
                reply_parts.append(
                    f"已为你导入并去重 **{res['added']}** 个目标仓库。"
                    + (" 请直接在下方 Gate 1 审批卡片中勾选要克隆并进入审计的项目。" if gate_card else "（这些仓库已在台账中，已自动跳过重复项。）")
                )
            except Exception as exc:
                ev_e = {"type": "tool_error", "tool": "scout_projects", "error": str(exc)}
                events.append(ev_e)
                yield ev_e
                reply_parts.append(f"导入失败：{exc}")
        elif any(k in user_text for k in ("推荐", "分配", "强项", "团队", "哪些agent", "agent")):
            ev = {"type": "tool_call", "tool": "recommend_team_assignment", "args": {}}
            events.append(ev)
            yield ev
            res, _ = self._exec_tool("recommend_team_assignment", {})
            ev_r = {"type": "tool_result", "tool": "recommend_team_assignment", "result": res}
            events.append(ev_r)
            yield ev_r
            lines = ["根据当前电脑探测到的 Agent 能力画像与异构互审原则，推荐岗位分配如下：", ""]
            for st, info in res["recommended_assignments"].items():
                lines.append(
                    f"- **{info['role']}** (`{st}`) → `{info['display_name']}`（后端 `{info['backend']}`）：{info['reason']}"
                )
            lines.append("\n你可以前往左侧 **「编排画布」** 点击一键应用该方案，或在 **「Agent 能力中心」** 配置 API Key 启用完整自然语言对话规划。")
            reply_parts.append("\n".join(lines))
        elif any(k in user_text for k in ("找", "搜", "scout", "项目", "github", "gitee", "gitcode")):
            platform = "gitee" if "gitee" in user_text.lower() else ("gitcode" if "gitcode" in user_text.lower() else "github")
            m_num = re.search(r"(\d+)\s*个", user_text)
            limit = min(int(m_num.group(1)), 15) if m_num else 5
            kw = "ai agent" if "ai" in user_text.lower() else ("web admin" if "web" in user_text.lower() else "security")
            args = {"platform": platform, "query": kw, "limit": limit}
            ev = {"type": "tool_call", "tool": "scout_projects", "args": args}
            events.append(ev)
            yield ev
            try:
                res, gc = self._exec_tool("scout_projects", args)
                gate_card = gc or gate_card
                ev_r = {"type": "tool_result", "tool": "scout_projects", "result": res}
                events.append(ev_r)
                yield ev_r
                reply_parts.append(f"已从 **{platform}** 搜索 `{kw}` 并入库 **{res['added']}** 个新项目，请在下方卡片勾选 Gate 1 审批。")
            except Exception as exc:
                ev_e = {"type": "tool_error", "tool": "scout_projects", "error": str(exc)}
                events.append(ev_e)
                yield ev_e
                reply_parts.append(f"搜索失败：{exc}（你也可以直接粘贴 GitHub/Gitee 仓库 URL 让我导入，或在「Agent 能力中心」配置 API Key 开启完整对话调度。）")
        else:
            ev = {"type": "tool_call", "tool": "list_pipeline_status", "args": {}}
            events.append(ev)
            yield ev
            res, _ = self._exec_tool("list_pipeline_status", {})
            ev_r = {"type": "tool_result", "tool": "list_pipeline_status", "result": res}
            events.append(ev_r)
            yield ev_r
            mention_note = f"（已识别你点名了 `@{', @'.join(mentions)}`）" if mentions else ""
            reply_parts.append(
                f"当前工作区共有 **{len(res['targets'])}** 个跟踪目标、**{len(res['candidates'])}** 个漏洞候选{mention_note}。\n\n"
                "你可以直接对我说：\n"
                "- **“帮我在 GitHub 找 5 个 AI Agent 项目”** 或直接粘贴 GitHub/Gitee 仓库链接导入\n"
                "- **“按强项帮我推荐一套 Agent 团队分配方案”**\n"
                "- 在左侧 **「Agent 能力中心 → API Providers」** 填入 DeepSeek / OpenAI / Qwen Key 后，我将自动切换为完整 ReAct 自由规划模式，支持多轮追问与跨 Agent 自动派活。"
            )

        final_text = "\n\n".join(reply_parts)
        saved = self.chat_store.append_message(
            session_id,
            role="assistant",
            agent_name="Coordinator",
            content=final_text,
            events=events,
            gate_card=gate_card,
        )
        yield {"type": "message", "message": saved}
        yield {"type": "done"}

    def _run_llm_react(
        self,
        session_id: str,
        user_text: str,
        mentions: list[str],
        llm: tuple[str, str, str],
    ) -> Iterator[dict[str, Any]]:
        base_url, api_key, model = llm
        profiles = discover_agent_profiles(
            self.pipeline,
            overrides_path=self.overrides_path,
            providers_path=self.providers_path,
        )
        team_summary = "\n".join(
            f"- {p.name} ({p.display_name}): enabled={p.enabled}, detected={p.detected}, strengths={p.capabilities}, backend={p.preferred_backend}"
            for p in profiles
        )
        system_prompt = (
            "你是 AuditFlow 的主理人（Coordinator Agent），负责根据不同 Agent 的能力强项组织开源代码安全审计、隔离环境验证与 CNVD 披露报告生成。\n"
            "原则：\n"
            "1. 优先调用工具完成真实操作，绝不编造仓库或漏洞结果；\n"
            "2. 严格尊重 Gate 1（选项目）与 Gate 2（选高价值漏洞）人工审批；\n"
            "3. 语言自然精炼、直接给出结论与下一步动作，拒绝官僚/人机腔。\n\n"
            f"当前可用 Agent 能力档案：\n{team_summary}\n"
            + (f"\n用户本次显式点名了：@{', @'.join(mentions)}" if mentions else "")
        )

        history = self.chat_store.get_messages(session_id)[-10:]
        messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
        for m in history:
            messages.append({"role": m["role"], "content": m["content"]})

        events: list[dict[str, Any]] = []
        gate_card: dict[str, Any] | None = None
        final_text = ""

        try:
            with httpx.Client(timeout=60) as client:
                for _step in range(4):
                    resp = client.post(
                        f"{base_url}/chat/completions",
                        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                        json={
                            "model": model,
                            "messages": messages,
                            "tools": COORDINATOR_TOOLS,
                            "tool_choice": "auto",
                            "temperature": 0.2,
                        },
                    )
                    if not resp.is_success:
                        raise ValueError(f"LLM API HTTP {resp.status_code}: {resp.text[:200]}")
                    msg = resp.json()["choices"][0]["message"]
                    tool_calls = msg.get("tool_calls") or []
                    if not tool_calls:
                        final_text = msg.get("content") or "已完成。"
                        break
                    messages.append(msg)
                    for tc in tool_calls:
                        fn_name = tc["function"]["name"]
                        raw_args = tc["function"].get("arguments") or "{}"
                        args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                        ev_call = {"type": "tool_call", "tool": fn_name, "args": args}
                        events.append(ev_call)
                        yield ev_call
                        try:
                            tool_res, gc = self._exec_tool(fn_name, args)
                            if gc is not None:
                                gate_card = gc
                            ev_res = {"type": "tool_result", "tool": fn_name, "result": tool_res}
                            events.append(ev_res)
                            yield ev_res
                            messages.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": tc["id"],
                                    "content": json.dumps(tool_res, ensure_ascii=False),
                                }
                            )
                        except Exception as exc:
                            ev_err = {"type": "tool_error", "tool": fn_name, "error": str(exc)}
                            events.append(ev_err)
                            yield ev_err
                            messages.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": tc["id"],
                                    "content": json.dumps({"error": str(exc)}, ensure_ascii=False),
                                }
                            )
                else:
                    final_text = "已完成多步工具调用，请查看上方执行记录与审批卡片。"
        except Exception as exc:
            final_text = f"Coordinator 调用模型失败：{exc}（请检查「Agent 能力中心 → API Providers」中的配置）。"

        saved = self.chat_store.append_message(
            session_id,
            role="assistant",
            agent_name=f"Coordinator ({model})",
            content=final_text,
            events=events,
            gate_card=gate_card,
        )
        yield {"type": "message", "message": saved}
        yield {"type": "done"}
