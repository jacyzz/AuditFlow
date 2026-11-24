import { useEffect, useState } from 'react'
import {
  ArrowRight,
  Bot,
  Cpu,
  Layers,
  Save,
  ShieldCheck,
  Sparkles,
  Wand2,
} from 'lucide-react'
import { api, CAPABILITY_LABELS, STAGE_META } from '../api'

interface Props {
  overview: any
  onRefresh: () => Promise<void>
  toast: (msg: string) => void
}

const FLOW_ROW_1 = ['scout', 'triage_project', 'surface_map', 'deep_audit'] as const
const FLOW_ROW_2 = ['triage_vuln', 'verify', 'evidence', 'report'] as const

export default function WorkflowStudio({ onRefresh, toast }: Props) {
  const [stages, setStages] = useState<Record<string, any>>({})
  const [profiles, setProfiles] = useState<any[]>([])
  const [recommendations, setRecommendations] = useState<Record<string, any>>({})
  const [skillsByStage, setSkillsByStage] = useState<Record<string, any[]>>({})
  const [selectedStage, setSelectedStage] = useState<string>('deep_audit')
  const [saving, setSaving] = useState(false)

  const loadData = async () => {
    try {
      const [cfg, prof, sk] = await Promise.all([
        api<any>('/api/config'),
        api<any>('/api/agents/profiles'),
        api<any>('/api/skills'),
      ])
      setStages(cfg.pipeline.stages || {})
      setProfiles(prof.profiles || [])
      setRecommendations(prof.recommendations || {})
      const grouped: Record<string, any[]> = {}
      for (const s of sk.skills || []) {
        grouped[s.stage] = grouped[s.stage] || []
        grouped[s.stage].push(s)
      }
      setSkillsByStage(grouped)
    } catch (e: any) {
      toast('加载编排画布失败: ' + e.message)
    }
  }

  useEffect(() => {
    loadData()
  }, [])

  const applyRecommended = () => {
    const next = { ...stages }
    for (const [st, rec] of Object.entries(recommendations)) {
      if (!next[st] || st === 'evidence') continue
      next[st] = {
        ...next[st],
        adapter: rec.adapter,
        backend: rec.backend,
      }
    }
    setStages(next)
    toast('已按 Agent 能力画像与异构互审规则填充最优方案，点击右上角保存生效')
  }

  const savePipeline = async () => {
    setSaving(true)
    try {
      const adapters: Record<string, any> = {}
      const custom_adapters: Record<string, any> = {}
      const builtins = new Set(['openai-api', 'dsh', 'codex', 'claude-code'])
      for (const p of profiles) {
        if (!p.enabled || p.name === 'native-subagent') continue
        if (builtins.has(p.name)) adapters[p.name] = p.adapter_config || {}
        else custom_adapters[p.name] = p.adapter_config || { type: 'custom-cli' }
      }
      await api('/api/config/apply-visual', 'POST', { adapters, custom_adapters, stages })
      toast('已校验并保存编排到 config/pipeline.yaml')
      await onRefresh()
    } catch (e: any) {
      toast('保存失败: ' + e.message)
    } finally {
      setSaving(false)
    }
  }

  const updateStage = (stage: string, patch: Record<string, any>) => {
    setStages((prev) => ({ ...prev, [stage]: { ...prev[stage], ...patch } }))
  }

  const enabledProfiles = profiles.filter((p) => p.enabled)
  const heteroOk =
    stages.deep_audit?.adapter &&
    stages.triage_vuln?.adapter &&
    stages.deep_audit.adapter !== stages.triage_vuln.adapter

  const renderNode = (stageKey: string) => {
    const meta = STAGE_META[stageKey]
    const cfg = stages[stageKey] || {}
    const active = selectedStage === stageKey
    const agentObj = profiles.find((p) => p.name === cfg.adapter)
    const rec = recommendations[stageKey]
    const skillLabel =
      stageKey === 'evidence'
        ? (cfg.renderers || []).join(' · ')
        : cfg.skills?.length
          ? `${cfg.skills.length} 个并发 Skill`
          : cfg.skill || '未选择'

    return (
      <button
        key={stageKey}
        onClick={() => setSelectedStage(stageKey)}
        className={`relative flex w-56 flex-col rounded-2xl border p-4 text-left transition ${
          active
            ? 'border-sky-400 bg-sky-500/10 shadow-lg shadow-sky-500/10'
            : 'border-[var(--border)] bg-[var(--surface)] hover:border-sky-500/50'
        }`}
      >
        <div className="flex items-center justify-between">
          <span className="rounded-md bg-sky-500/15 px-2 py-0.5 text-[11px] font-semibold text-sky-400">
            {meta.role}
          </span>
          <span className="rounded bg-[var(--surface-2)] px-1.5 py-0.5 font-mono text-[10px] text-[var(--muted)]">
            {cfg.backend || 'local'}
          </span>
        </div>
        <div className="mt-2.5 text-sm font-bold">{meta.label}</div>
        <div className="mt-0.5 text-[11px] text-[var(--muted)]">{meta.desc}</div>

        <div className="mt-3 space-y-1.5 border-t border-[var(--border)] pt-2.5 text-xs">
          <div className="flex items-center justify-between">
            <span className="flex items-center gap-1 text-[var(--muted)]">
              <Bot className="h-3.5 w-3.5" /> Agent
            </span>
            <span className="font-semibold text-emerald-400">
              {stageKey === 'evidence' ? '确定性脚本' : agentObj?.name || cfg.adapter || '-'}
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span className="flex items-center gap-1 text-[var(--muted)]">
              <Layers className="h-3.5 w-3.5" /> Skill
            </span>
            <span className="max-w-[125px] truncate text-[11px]">{skillLabel}</span>
          </div>
        </div>

        {rec && stageKey !== 'evidence' && rec.adapter === cfg.adapter && (
          <div className="mt-2 flex items-center gap-1 text-[10px] text-sky-400">
            <Sparkles className="h-3 w-3" /> 能力匹配最优（{rec.score}分）
          </div>
        )}
      </button>
    )
  }

  const curCfg = stages[selectedStage] || {}
  const curSkills = skillsByStage[selectedStage] || []
  const curRec = recommendations[selectedStage]

  return (
    <div className="grid h-full grid-cols-[1fr_370px] overflow-hidden">
      {/* Visual Canvas */}
      <div className="flex flex-col overflow-auto bg-[var(--bg)] p-6">
        <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-lg font-bold">多 Agent 能力编排画布（Workflow Studio）</h1>
            <p className="text-xs text-[var(--muted)]">
              点击任意节点调整绑定的 Agent、Skill 与执行主机；系统自动校验主审与复核是否构成异构互审
            </p>
          </div>
          <div className="flex gap-2">
            <button
              onClick={applyRecommended}
              className="flex items-center gap-1.5 rounded-xl border border-sky-500/40 bg-sky-500/15 px-3.5 py-2 text-xs font-semibold text-sky-400 hover:bg-sky-500/25"
            >
              <Wand2 className="h-4 w-4" /> 按 Agent 强项一键最优分配
            </button>
            <button
              disabled={saving}
              onClick={savePipeline}
              className="flex items-center gap-1.5 rounded-xl bg-emerald-600 px-4 py-2 text-xs font-semibold text-white hover:bg-emerald-500 disabled:opacity-50"
            >
              <Save className="h-4 w-4" /> 保存到 pipeline.yaml
            </button>
          </div>
        </div>

        {/* Heterogeneous Cross-Review Banner */}
        <div
          className={`mb-6 flex items-center justify-between rounded-xl border px-4 py-2.5 text-xs ${
            heteroOk
              ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
              : 'border-amber-500/30 bg-amber-500/10 text-amber-300'
          }`}
        >
          <span className="flex items-center gap-2">
            <ShieldCheck className="h-4 w-4" />
            {heteroOk
              ? `异构互审已生效：主审 (${stages.deep_audit?.adapter}) ≠ 复核 (${stages.triage_vuln?.adapter})，有效降低单一模型盲区`
              : `提示：当前主审 (${stages.deep_audit?.adapter || '-'}) 与复核 (${stages.triage_vuln?.adapter || '-'}) 使用了同一 Agent，建议点击「一键最优分配」开启异构互审`}
          </span>
        </div>

        {/* Canvas Grid with Connectors & Gates */}
        <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface-2)]/50 p-6">
          <div className="mb-3 text-xs font-semibold uppercase tracking-wider text-[var(--muted)]">
            阶段 I · 发现、筛查与源码深审
          </div>
          <div className="flex flex-wrap items-center gap-3">
            {FLOW_ROW_1.map((st, idx) => (
              <div key={st} className="flex items-center gap-3">
                {renderNode(st)}
                {idx === 1 && (
                  <div className="flex flex-col items-center rounded-xl border border-amber-500/40 bg-amber-500/15 px-3 py-2 text-[11px] font-semibold text-amber-400">
                    <span>Gate 1</span>
                    <span className="text-[10px] font-normal">人工选项目</span>
                  </div>
                )}
                {idx < FLOW_ROW_1.length - 1 && <ArrowRight className="h-4 w-4 text-[var(--muted)]" />}
              </div>
            ))}
          </div>

          <div className="my-6 flex items-center gap-3">
            <div className="h-px flex-1 bg-[var(--border)]" />
            <div className="rounded-full border border-amber-500/40 bg-amber-500/15 px-4 py-1 text-xs font-semibold text-amber-400">
              ↓ Gate 2：人工勾选高价值漏洞候选（过滤低价值与已知 CVE） ↓
            </div>
            <div className="h-px flex-1 bg-[var(--border)]" />
          </div>

          <div className="mb-3 text-xs font-semibold uppercase tracking-wider text-[var(--muted)]">
            阶段 II · 异构复核、隔离验证与 CNVD 交付
          </div>
          <div className="flex flex-wrap items-center gap-3">
            {FLOW_ROW_2.map((st, idx) => (
              <div key={st} className="flex items-center gap-3">
                {renderNode(st)}
                {idx < FLOW_ROW_2.length - 1 && <ArrowRight className="h-4 w-4 text-[var(--muted)]" />}
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Right Node Inspector */}
      <aside className="flex flex-col overflow-y-auto border-l border-[var(--border)] bg-[var(--surface)] p-5">
        <div className="flex items-center gap-2 border-b border-[var(--border)] pb-3">
          <Cpu className="h-4 w-4 text-sky-400" />
          <div>
            <div className="text-sm font-bold">{STAGE_META[selectedStage]?.label}</div>
            <div className="text-xs text-[var(--muted)]">
              岗位：{STAGE_META[selectedStage]?.role} · 节点 `{selectedStage}`
            </div>
          </div>
        </div>

        {curRec && selectedStage !== 'evidence' && (
          <div className="mt-4 rounded-xl border border-sky-500/30 bg-sky-500/10 p-3 text-xs">
            <div className="font-semibold text-sky-400">系统推荐：{curRec.display_name}</div>
            <div className="mt-1 text-[var(--muted)]">{curRec.reason}</div>
          </div>
        )}

        <div className="mt-4 space-y-4 text-xs">
          {selectedStage !== 'evidence' && (
            <div>
              <label className="mb-1.5 block font-semibold">分配执行 Agent</label>
              <select
                value={curCfg.adapter || ''}
                onChange={(e) => updateStage(selectedStage, { adapter: e.target.value })}
                className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-xs"
              >
                {(enabledProfiles.length ? enabledProfiles : profiles).map((p) => (
                  <option key={p.name} value={p.name}>
                    {p.display_name} ({p.name}) {p.detected ? '· 已就绪' : '· 远端/待配置'}
                  </option>
                ))}
              </select>
              {(() => {
                const chosen = profiles.find((p) => p.name === curCfg.adapter)
                if (!chosen) return null
                return (
                  <div className="mt-2 flex flex-wrap gap-1">
                    {(chosen.capabilities || []).map((cap: string) => (
                      <span
                        key={cap}
                        className="rounded-full bg-[var(--surface-2)] px-2 py-0.5 text-[10px] text-[var(--muted)]"
                      >
                        {CAPABILITY_LABELS[cap] || cap}
                      </span>
                    ))}
                  </div>
                )
              })()}
            </div>
          )}

          <div>
            <label className="mb-1.5 block font-semibold">
              {selectedStage === 'evidence'
                ? '启用的确定性渲染器'
                : selectedStage === 'deep_audit'
                  ? '并发审计子 Skill（可多选）'
                  : '绑定 Skill'}
            </label>
            {selectedStage === 'evidence' ? (
              <div className="space-y-1.5">
                {['code', 'web', 'http', 'term'].map((r) => {
                  const active = (curCfg.renderers || []).includes(r)
                  return (
                    <label
                      key={r}
                      className="flex cursor-pointer items-center gap-2 rounded-lg border border-[var(--border)] bg-[var(--surface-2)] px-3 py-2"
                    >
                      <input
                        type="checkbox"
                        checked={active}
                        onChange={(e) => {
                          const prev = new Set(curCfg.renderers || [])
                          if (e.target.checked) prev.add(r)
                          else prev.delete(r)
                          updateStage(selectedStage, { renderers: Array.from(prev) })
                        }}
                      />
                      <span className="font-mono">{r}</span>
                    </label>
                  )
                })}
              </div>
            ) : selectedStage === 'deep_audit' ? (
              <div className="space-y-1.5">
                {curSkills.map((s) => {
                  const list: string[] = curCfg.skills?.length
                    ? curCfg.skills
                    : curCfg.skill
                      ? [curCfg.skill]
                      : []
                  const active = list.includes(s.name)
                  return (
                    <label
                      key={s.name}
                      className="flex cursor-pointer items-start gap-2 rounded-lg border border-[var(--border)] bg-[var(--surface-2)] px-3 py-2"
                    >
                      <input
                        type="checkbox"
                        checked={active}
                        onChange={(e) => {
                          const set = new Set(list)
                          if (e.target.checked) set.add(s.name)
                          else set.delete(s.name)
                          updateStage(selectedStage, { skills: Array.from(set), skill: undefined })
                        }}
                        className="mt-0.5"
                      />
                      <div>
                        <div className="font-semibold">{s.name}</div>
                        <div className="text-[11px] text-[var(--muted)]">{s.description}</div>
                      </div>
                    </label>
                  )
                })}
              </div>
            ) : (
              <select
                value={curCfg.skill || ''}
                onChange={(e) => updateStage(selectedStage, { skill: e.target.value, skills: [] })}
                className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-xs"
              >
                {curSkills.map((s) => (
                  <option key={s.name} value={s.name}>
                    {s.name} — {s.description}
                  </option>
                ))}
              </select>
            )}
          </div>

          <div>
            <label className="mb-1.5 block font-semibold">执行主机（Backend）</label>
            <select
              value={curCfg.backend || 'local'}
              onChange={(e) => updateStage(selectedStage, { backend: e.target.value })}
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-xs"
            >
              <option value="local">local（当前 Windows 本机）</option>
              <option value="ssh-ubuntu">ssh-ubuntu（Ubuntu2404 隔离虚拟机）</option>
              <option value="wsl2">wsl2（本机 WSL2 Linux）</option>
            </select>
          </div>

          <div>
            <label className="mb-1.5 block font-semibold">阶段超时（秒）</label>
            <input
              type="number"
              min={10}
              max={86400}
              value={curCfg.timeout_sec || 300}
              onChange={(e) => updateStage(selectedStage, { timeout_sec: Number(e.target.value || 300) })}
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-xs"
            />
          </div>

          {selectedStage === 'verify' && (
            <div>
              <label className="mb-1.5 block font-semibold">Docker 环境排错最大重试次数（熔断上限）</label>
              <input
                type="number"
                min={0}
                max={10}
                value={curCfg.max_env_retries ?? 2}
                onChange={(e) => updateStage(selectedStage, { max_env_retries: Number(e.target.value) })}
                className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-xs"
              />
            </div>
          )}
        </div>
      </aside>
    </div>
  )
}
