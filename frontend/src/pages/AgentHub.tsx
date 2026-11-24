import { useEffect, useState } from 'react'
import {
  Check,
  CheckCircle2,
  Cpu,
  FolderOpen,
  KeyRound,
  Plus,
  RefreshCw,
  Stethoscope,
  Trash2,
  Wifi,
} from 'lucide-react'
import { api } from '../api'
import { AgentIcon } from '../components/AgentIcon'
import {
  Button,
  Field,
  Input,
  Modal,
  SegmentedControl,
  Select,
  StatusPill,
  Switch,
  cn,
} from '../components/ui'

interface Props {
  toast: (msg: string) => void
  onRefresh: () => Promise<void>
  dark: boolean
}

const CAPABILITY_LABELS: Record<string, { label: string; desc: string }> = {
  deep_reasoning: { label: '深度推理', desc: '复杂跨文件污点与鉴权链分析' },
  docker_verify: { label: 'Docker 验证', desc: '容器编排、抓包与隔离复现' },
  bulk_triage: { label: '批量初筛', desc: '低成本快速筛选项目与候选' },
  cn_writing: { label: '中文披露写作', desc: '自然专业中文 CNVD 报告' },
  tool_use: { label: 'CLI 工具链', desc: '读写文件、执行命令与代码检索' },
  long_context: { label: '长上下文', desc: '大仓库跨模块关联阅读' },
}

const COST_LABELS: Record<string, string> = {
  free: '免费 / 宿主内置',
  low: '低成本',
  medium: '中等',
  high: '高算力',
}

export default function AgentHub({ toast, onRefresh, dark }: Props) {
  const [tab, setTab] = useState<'agents' | 'providers' | 'doctor'>('agents')
  const [profiles, setProfiles] = useState<any[]>([])
  const [selectedName, setSelectedName] = useState<string>('')
  const [providers, setProviders] = useState<any[]>([])
  const [presets, setPresets] = useState<any[]>([])
  const [doctor, setDoctor] = useState<any>(null)
  const [testingId, setTestingId] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  // Modals
  const [showCustomModal, setShowCustomModal] = useState(false)
  const [customForm, setCustomForm] = useState({
    name: '',
    display_name: '',
    command_template: '',
    description: '',
  })

  const [showProviderModal, setShowProviderModal] = useState(false)
  const [providerForm, setProviderForm] = useState({
    id: '',
    name: '',
    preset: 'deepseek',
    base_url: 'https://api.deepseek.com/v1',
    api_key_env: 'DEEPSEEK_API_KEY',
    api_key_inline: '',
    default_model: 'deepseek-chat',
    models: 'deepseek-chat, deepseek-reasoner',
    is_coordinator_default: true,
    enabled: true,
  })

  const loadAll = async () => {
    setLoading(true)
    try {
      const [pRes, provRes, docRes] = await Promise.all([
        api<any>('/api/agents/profiles'),
        api<any>('/api/providers'),
        api<any>('/api/doctor'),
      ])
      const list = pRes.profiles || []
      setProfiles(list)
      setSelectedName((prev) => (prev && list.some((x: any) => x.name === prev) ? prev : list[0]?.name || ''))
      setProviders(provRes.providers || [])
      setPresets(provRes.presets || [])
      setDoctor(docRes)
    } catch (e: any) {
      toast('加载 Agent 能力中心失败: ' + e.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadAll()
  }, [])

  const selected = profiles.find((p) => p.name === selectedName) || profiles[0]

  const patchProfile = async (name: string, patch: Record<string, any>) => {
    try {
      await api(`/api/agents/profiles/${encodeURIComponent(name)}`, 'POST', patch)
      setProfiles((prev) => prev.map((p) => (p.name === name ? { ...p, ...patch } : p)))
      await onRefresh()
      toast(`已更新 ${name} 配置`)
    } catch (e: any) {
      toast('更新失败: ' + e.message)
    }
  }

  const toggleCapability = (agent: any, cap: string) => {
    const cur: string[] = agent.capabilities || []
    const next = cur.includes(cap) ? cur.filter((c) => c !== cap) : [...cur, cap]
    patchProfile(agent.name, { capabilities: next })
  }

  const addCustomAgent = async () => {
    if (!customForm.name.trim() || !customForm.command_template.trim()) {
      toast('请填写适配器标识和命令模板')
      return
    }
    try {
      await api('/api/agents/custom', 'POST', customForm)
      toast(`已注册自定义 Agent：${customForm.name}`)
      setShowCustomModal(false)
      setCustomForm({ name: '', display_name: '', command_template: '', description: '' })
      await loadAll()
      await onRefresh()
    } catch (e: any) {
      toast('注册失败: ' + e.message)
    }
  }

  const applyPreset = (preset: any) => {
    setProviderForm({
      id: preset.preset === 'custom' ? `custom-${Date.now().toString().slice(-4)}` : preset.preset,
      name: preset.name,
      preset: preset.preset,
      base_url: preset.base_url,
      api_key_env: preset.api_key_env,
      api_key_inline: '',
      default_model: preset.default_model,
      models: (preset.models || []).join(', '),
      is_coordinator_default: providers.length === 0,
      enabled: true,
    })
    setShowProviderModal(true)
  }

  const saveProvider = async () => {
    if (!providerForm.id.trim() || !providerForm.base_url.trim() || !providerForm.default_model.trim()) {
      toast('请填写 Provider ID、Base URL 和默认模型')
      return
    }
    try {
      await api('/api/providers', 'POST', {
        ...providerForm,
        models: providerForm.models
          .split(',')
          .map((s) => s.trim())
          .filter(Boolean),
        api_key_inline: providerForm.api_key_inline.trim() || null,
      })
      toast(`已保存 Provider：${providerForm.name}`)
      setShowProviderModal(false)
      await loadAll()
      await onRefresh()
    } catch (e: any) {
      toast('保存失败: ' + e.message)
    }
  }

  const testProvider = async (id: string) => {
    setTestingId(id)
    try {
      const res = await api<any>(`/api/providers/${encodeURIComponent(id)}/test`, 'POST')
      toast(res.ok ? `连接成功：${res.detail}` : `连接失败：${res.detail}`)
    } catch (e: any) {
      toast('测试失败: ' + e.message)
    } finally {
      setTestingId(null)
    }
  }

  const deleteProvider = async (id: string) => {
    try {
      await api(`/api/providers/${encodeURIComponent(id)}`, 'DELETE')
      toast('已移除 API Provider')
      await loadAll()
    } catch (e: any) {
      toast('移除失败: ' + e.message)
    }
  }

  const getStatusMeta = (agent: any) => {
    if (agent.detected) return { tone: 'ok' as const, label: '已就绪' }
    if (agent.native_config_exists || agent.kind === 'api') return { tone: 'warn' as const, label: '需配置' }
    return { tone: 'neutral' as const, label: '未安装' }
  }

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Compact Tahoe Header */}
      <div className="flex items-center justify-between border-b border-[var(--border)] px-6 py-3.5">
        <div>
          <h1 className="text-[16px] font-semibold tracking-[-0.015em]">Agent 能力中心</h1>
          <p className="mt-0.5 text-xs text-[var(--muted)]">
            勾选要启用的出战 Agent，点击名称查看状态、只读原生配置与能力强项
          </p>
        </div>
        <div className="flex items-center gap-2">
          <SegmentedControl
            value={tab}
            onChange={setTab}
            options={[
              { value: 'agents', label: '出战 Agent', icon: <Cpu className="h-3.5 w-3.5" /> },
              {
                value: 'providers',
                label: `API Providers${providers.length ? ` (${providers.length})` : ''}`,
                icon: <KeyRound className="h-3.5 w-3.5" />,
              },
              { value: 'doctor', label: '环境体检', icon: <Stethoscope className="h-3.5 w-3.5" /> },
            ]}
          />
          <Button variant="secondary" onClick={loadAll}>
            <RefreshCw className={cn('h-3.5 w-3.5', loading && 'animate-spin')} />
            重新探测
          </Button>
          <Button variant="primary" onClick={() => setShowCustomModal(true)}>
            <Plus className="h-3.5 w-3.5" />
            接入自定义 CLI
          </Button>
        </div>
      </div>

      {/* ── Tab 1: Dimo Master-Detail Agent Roster ────────────────── */}
      {tab === 'agents' && (
        <div className="flex flex-1 overflow-hidden bg-[var(--surface-subtle)]">
          {/* Left Inset Grouped List (Dimo-style) */}
          <div className="w-[380px] shrink-0 overflow-y-auto border-r border-[var(--border)] p-5">
            <div className="mb-2 flex items-center justify-between px-1">
              <span className="text-xs font-medium text-[var(--muted)]">本机与 API Agent 名册</span>
              <span className="text-[11px] text-[var(--subtle)]">
                {profiles.filter((p) => p.enabled).length} / {profiles.length} 已启用
              </span>
            </div>

            <div className="tahoe-card overflow-hidden">
              {profiles.map((agent) => {
                const isSelected = selected?.name === agent.name
                const st = getStatusMeta(agent)
                return (
                  <div
                    key={agent.name}
                    onClick={() => setSelectedName(agent.name)}
                    className={cn(
                      'flex items-center justify-between gap-3 px-3.5 py-2.5 transition-colors duration-150 cursor-pointer',
                      isSelected ? 'bg-[var(--surface-active)]' : 'hover:bg-[var(--surface-hover)]',
                    )}
                  >
                    <div className="flex min-w-0 items-center gap-3">
                      {/* Circular Ink Checkbox (Dimo signature) */}
                      <button
                        type="button"
                        title={agent.enabled ? '停用' : '启用'}
                        onClick={(e) => {
                          e.stopPropagation()
                          patchProfile(agent.name, { enabled: !agent.enabled })
                        }}
                        className={cn(
                          'flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-full border transition-colors cursor-pointer',
                          agent.enabled
                            ? 'border-[var(--primary)] bg-[var(--primary)] text-[var(--primary-fg)]'
                            : 'border-[var(--border-strong)] bg-transparent hover:border-[var(--muted)]',
                        )}
                      >
                        {agent.enabled && <Check className="h-3 w-3 stroke-[2.8]" />}
                      </button>

                      <AgentIcon agent={agent.name} dark={dark} size={20} />

                      <div className="min-w-0">
                        <div className="truncate text-[13.5px] font-medium text-[var(--fg)]">
                          {agent.display_name}
                        </div>
                        <div className="truncate text-[11px] text-[var(--muted)]">
                          {agent.vendor} · {COST_LABELS[agent.cost_tier] || agent.cost_tier}
                        </div>
                      </div>
                    </div>

                    <StatusPill tone={st.tone} dot={st.tone === 'ok'}>
                      {st.label}
                    </StatusPill>
                  </div>
                )
              })}
            </div>

            <p className="mt-3 px-1 text-[11.5px] leading-relaxed text-[var(--muted)]">
              只读原则：AuditFlow 仅检查本机 CLI 可执行文件与原生配置路径是否存在，绝不修改
              <code className="mx-1 font-mono">~/.codex</code>、
              <code className="mx-1 font-mono">~/.claude</code> 等原生配置。
            </p>
          </div>

          {/* Right Detail Inspector Pane (Dimo-style) */}
          <div className="flex-1 overflow-y-auto bg-[var(--surface)] p-7">
            {selected ? (
              <div className="mx-auto max-w-2xl space-y-6">
                {/* Identity Row */}
                <div className="flex items-start justify-between gap-4">
                  <div className="flex items-center gap-3.5">
                    <div className="flex h-11 w-11 items-center justify-center rounded-[12px] border border-[var(--border)] bg-[var(--surface-subtle)]">
                      <AgentIcon agent={selected.name} dark={dark} size={26} />
                    </div>
                    <div>
                      <div className="flex items-center gap-2.5">
                        <h2 className="text-[17px] font-semibold tracking-[-0.015em]">
                          {selected.display_name}
                        </h2>
                        <StatusPill tone={getStatusMeta(selected).tone} dot={selected.detected}>
                          {getStatusMeta(selected).label}
                        </StatusPill>
                      </div>
                      <p className="mt-0.5 text-xs text-[var(--muted)]">
                        {selected.vendor} · 适配器标识 <code className="font-mono">{selected.name}</code>
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-2.5">
                    <span className="text-xs text-[var(--muted)]">
                      {selected.enabled ? '参与编排' : '未启用'}
                    </span>
                    <Switch
                      checked={Boolean(selected.enabled)}
                      onChange={(v) => patchProfile(selected.name, { enabled: v })}
                    />
                  </div>
                </div>

                {selected.description && (
                  <p className="text-[13px] leading-relaxed text-[var(--fg-secondary)]">
                    {selected.description}
                  </p>
                )}

                {/* Section 1: Read-Only Discovery & Native Path */}
                <div className="tahoe-card divide-y divide-[var(--border)]">
                  <div className="flex items-center justify-between px-4 py-3">
                    <div>
                      <div className="text-xs font-medium text-[var(--fg)]">可用状态与探测详情</div>
                      <div className="mt-0.5 text-xs text-[var(--muted)]">
                        {selected.status_detail || '已完成本机只读扫描'}
                      </div>
                    </div>
                    <Button size="sm" variant="secondary" onClick={loadAll}>
                      <RefreshCw className="h-3 w-3" /> 检查可用状态
                    </Button>
                  </div>

                  {selected.binary_path && (
                    <div className="flex items-center justify-between gap-3 px-4 py-2.5 text-xs">
                      <span className="text-[var(--muted)]">可执行路径</span>
                      <code className="truncate font-mono text-[11.5px] text-[var(--fg-secondary)]">
                        {selected.binary_path}
                      </code>
                    </div>
                  )}

                  {selected.native_config_path && (
                    <div className="flex items-center justify-between gap-3 px-4 py-2.5 text-xs">
                      <span className="flex items-center gap-1.5 text-[var(--muted)]">
                        <FolderOpen className="h-3.5 w-3.5" /> 原生配置路径（只读）
                      </span>
                      <code className="truncate font-mono text-[11.5px] text-[var(--fg-secondary)]">
                        {selected.native_config_path}
                        {selected.native_config_exists ? ' · 已存在' : ' · 未发现'}
                      </code>
                    </div>
                  )}
                </div>

                {/* Section 2: Capability Strengths */}
                <div className="tahoe-card p-4 space-y-3">
                  <div>
                    <div className="text-xs font-semibold text-[var(--fg)]">能力强项画像</div>
                    <div className="mt-0.5 text-xs text-[var(--muted)]">
                      「编排画布」一键最优分配将依据这些标签，并确保深度审计与漏洞复核由不同 Agent 异构互审
                    </div>
                  </div>
                  <div className="grid gap-2 sm:grid-cols-2">
                    {Object.entries(CAPABILITY_LABELS).map(([tag, meta]) => {
                      const active = (selected.capabilities || []).includes(tag)
                      return (
                        <button
                          key={tag}
                          type="button"
                          onClick={() => toggleCapability(selected, tag)}
                          className={cn(
                            'flex items-start justify-between gap-2 rounded-[10px] border px-3 py-2.5 text-left transition-colors cursor-pointer',
                            active
                              ? 'border-[var(--primary)] bg-[var(--surface-subtle)]'
                              : 'border-[var(--border)] bg-transparent hover:bg-[var(--surface-hover)]',
                          )}
                        >
                          <div>
                            <div className="text-xs font-medium text-[var(--fg)]">{meta.label}</div>
                            <div className="mt-0.5 text-[11px] text-[var(--muted)]">{meta.desc}</div>
                          </div>
                          <span
                            className={cn(
                              'mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full border',
                              active
                                ? 'border-[var(--primary)] bg-[var(--primary)] text-[var(--primary-fg)]'
                                : 'border-[var(--border-strong)]',
                            )}
                          >
                            {active && <Check className="h-2.5 w-2.5 stroke-[3]" />}
                          </span>
                        </button>
                      )
                    })}
                  </div>
                </div>

                {/* Section 3: Execution Backend & Cost Tier */}
                <div className="tahoe-card divide-y divide-[var(--border)]">
                  <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
                    <div>
                      <div className="text-xs font-medium text-[var(--fg)]">首选执行后端</div>
                      <div className="text-[11px] text-[var(--muted)]">
                        隔离验证与代码分析推荐优先运行在 Linux / Docker 主机
                      </div>
                    </div>
                    <SegmentedControl
                      value={selected.preferred_backend || 'local'}
                      onChange={(v) => patchProfile(selected.name, { preferred_backend: v })}
                      options={[
                        { value: 'local', label: 'local (本机)' },
                        { value: 'ssh-ubuntu', label: 'ssh-ubuntu' },
                        { value: 'wsl2', label: 'wsl2' },
                      ]}
                    />
                  </div>
                  <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
                    <div>
                      <div className="text-xs font-medium text-[var(--fg)]">成本档位</div>
                      <div className="text-[11px] text-[var(--muted)]">
                        用于初筛与批量任务路由时的成本权衡
                      </div>
                    </div>
                    <div className="w-40">
                      <Select
                        value={selected.cost_tier || 'medium'}
                        onChange={(e) => patchProfile(selected.name, { cost_tier: e.target.value })}
                      >
                        <option value="free">免费 / 宿主内置</option>
                        <option value="low">低成本</option>
                        <option value="medium">中等</option>
                        <option value="high">高算力</option>
                      </Select>
                    </div>
                  </div>
                </div>
              </div>
            ) : (
              <div className="flex h-full items-center justify-center text-sm text-[var(--muted)]">
                暂无 Agent 配置
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── Tab 2: API Providers ─────────────────────────────────── */}
      {tab === 'providers' && (
        <div className="flex-1 overflow-y-auto bg-[var(--surface-subtle)] p-6">
          <div className="mx-auto max-w-4xl space-y-6">
            <div>
              <div className="mb-2.5 text-xs font-medium text-[var(--muted)]">
                一键从预设添加 OpenAI 兼容服务商（驱动对话主理人与 openai-api 批量筛选）
              </div>
              <div className="grid gap-2.5 sm:grid-cols-3 lg:grid-cols-6">
                {presets.map((p) => (
                  <button
                    key={p.preset}
                    type="button"
                    onClick={() => applyPreset(p)}
                    className="tahoe-card flex flex-col items-start p-3 text-left transition-colors hover:bg-[var(--surface-hover)] cursor-pointer"
                  >
                    <div className="text-xs font-semibold text-[var(--fg)]">{p.name}</div>
                    <div className="mt-1 truncate w-full font-mono text-[10.5px] text-[var(--muted)]">
                      {p.default_model}
                    </div>
                  </button>
                ))}
              </div>
            </div>

            <div>
              <div className="mb-2.5 flex items-center justify-between">
                <span className="text-xs font-medium text-[var(--muted)]">
                  已配置的 API Providers（保存在本地 gitignored config/providers.yaml）
                </span>
                <Button
                  size="sm"
                  variant="primary"
                  onClick={() =>
                    applyPreset({
                      preset: 'custom',
                      name: '自定义服务商',
                      base_url: 'https://api.openai.com/v1',
                      api_key_env: 'AUDITFLOW_OPENAI_API_KEY',
                      default_model: 'gpt-4.1-mini',
                      models: ['gpt-4.1-mini'],
                    })
                  }
                >
                  <Plus className="h-3 w-3" /> 新增 Provider
                </Button>
              </div>

              {providers.length === 0 ? (
                <div className="tahoe-card p-10 text-center">
                  <KeyRound className="mx-auto h-7 w-7 text-[var(--subtle)]" />
                  <div className="mt-2.5 text-sm font-medium">尚未配置 API Provider</div>
                  <p className="mt-1 text-xs text-[var(--muted)]">
                    点击上方 DeepSeek / OpenAI / 通义千问 等预设，填入 Key 后即可开启完整 ReAct 对话规划。
                  </p>
                </div>
              ) : (
                <div className="tahoe-card divide-y divide-[var(--border)] overflow-hidden">
                  {providers.map((p) => (
                    <div
                      key={p.id}
                      className="flex flex-wrap items-center justify-between gap-4 px-4 py-3.5"
                    >
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="text-[13.5px] font-semibold">{p.name}</span>
                          {p.is_coordinator_default && (
                            <StatusPill tone="ok" dot>
                              主理人默认
                            </StatusPill>
                          )}
                          <StatusPill tone="neutral">{p.default_model}</StatusPill>
                        </div>
                        <div className="mt-1 truncate font-mono text-[11.5px] text-[var(--muted)]">
                          {p.base_url} · Key:{' '}
                          {p.has_inline_key ? p.api_key_inline : `env:${p.api_key_env}`}
                        </div>
                      </div>
                      <div className="flex items-center gap-2">
                        <Button
                          size="sm"
                          variant="secondary"
                          disabled={testingId === p.id}
                          onClick={() => testProvider(p.id)}
                        >
                          <Wifi className="h-3.5 w-3.5" />
                          {testingId === p.id ? '测试中...' : '测试连通性'}
                        </Button>
                        <Button size="sm" variant="ghost" onClick={() => deleteProvider(p.id)}>
                          <Trash2 className="h-3.5 w-3.5 text-[var(--danger)]" />
                        </Button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ── Tab 3: Doctor Checks ─────────────────────────────────── */}
      {tab === 'doctor' && (
        <div className="flex-1 overflow-y-auto bg-[var(--surface-subtle)] p-6">
          <div className="mx-auto max-w-3xl space-y-4">
            <div className="flex items-center justify-between">
              <div className="text-xs font-medium text-[var(--muted)]">
                适配器、后端连通性与运行依赖自检（auditflow doctor）
              </div>
              <Button size="sm" variant="secondary" onClick={loadAll}>
                <RefreshCw className="h-3 w-3" /> 重新检测
              </Button>
            </div>
            <div className="tahoe-card divide-y divide-[var(--border)] overflow-hidden">
              {(doctor?.checks || []).map((c: any, idx: number) => (
                <div key={idx} className="flex items-center justify-between gap-4 px-4 py-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 text-[13px] font-medium">
                      <CheckCircle2
                        className={cn(
                          'h-4 w-4 shrink-0',
                          c.ok ? 'text-[var(--ok)]' : 'text-[var(--warn)]',
                        )}
                      />
                      <span>{c.name}</span>
                    </div>
                    <div className="mt-0.5 pl-6 text-xs text-[var(--muted)]">{c.detail}</div>
                  </div>
                  <StatusPill tone={c.ok ? 'ok' : 'warn'}>{c.ok ? '正常' : '待配置'}</StatusPill>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Custom CLI Agent Modal */}
      <Modal
        open={showCustomModal}
        onClose={() => setShowCustomModal(false)}
        title="接入自定义本机 CLI Agent"
        description="零代码接入任何支持命令行调用的 Agent，支持占位符 {skill_path}、{workspace_dir}、{output_file}。"
        footer={
          <>
            <Button variant="secondary" onClick={() => setShowCustomModal(false)}>
              取消
            </Button>
            <Button variant="primary" onClick={addCustomAgent}>
              保存并注册
            </Button>
          </>
        }
      >
        <div className="space-y-3.5">
          <Field label="适配器标识" hint="仅小写字母、数字与连字符">
            <Input
              value={customForm.name}
              onChange={(e) => setCustomForm({ ...customForm, name: e.target.value })}
              placeholder="例如 my-local-auditor"
            />
          </Field>
          <Field label="显示名称">
            <Input
              value={customForm.display_name}
              onChange={(e) => setCustomForm({ ...customForm, display_name: e.target.value })}
              placeholder="例如 内部审计 Agent"
            />
          </Field>
          <Field label="命令模板">
            <Input
              className="font-mono"
              value={customForm.command_template}
              onChange={(e) => setCustomForm({ ...customForm, command_template: e.target.value })}
              placeholder="my-agent run --skill {skill_path} --out {output_file}"
            />
          </Field>
          <Field label="强项说明（可选）">
            <Input
              value={customForm.description}
              onChange={(e) => setCustomForm({ ...customForm, description: e.target.value })}
              placeholder="擅长 Go / Java 微服务鉴权审计"
            />
          </Field>
        </div>
      </Modal>

      {/* Add / Edit Provider Modal */}
      <Modal
        open={showProviderModal}
        onClose={() => setShowProviderModal(false)}
        title={`配置 API Provider · ${providerForm.name}`}
        description="仅保存在本机 gitignored 的 config/providers.yaml，接口返回时自动脱敏。"
        footer={
          <>
            <Button variant="secondary" onClick={() => setShowProviderModal(false)}>
              取消
            </Button>
            <Button variant="primary" onClick={saveProvider}>
              保存配置
            </Button>
          </>
        }
      >
        <div className="space-y-3.5">
          <div className="grid grid-cols-2 gap-3">
            <Field label="Provider ID">
              <Input
                value={providerForm.id}
                onChange={(e) => setProviderForm({ ...providerForm, id: e.target.value })}
              />
            </Field>
            <Field label="显示名称">
              <Input
                value={providerForm.name}
                onChange={(e) => setProviderForm({ ...providerForm, name: e.target.value })}
              />
            </Field>
          </div>
          <Field label="Base URL">
            <Input
              className="font-mono"
              value={providerForm.base_url}
              onChange={(e) => setProviderForm({ ...providerForm, base_url: e.target.value })}
            />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="默认模型">
              <Input
                className="font-mono"
                value={providerForm.default_model}
                onChange={(e) => setProviderForm({ ...providerForm, default_model: e.target.value })}
              />
            </Field>
            <Field label="环境变量名（可选兜底）">
              <Input
                className="font-mono"
                value={providerForm.api_key_env}
                onChange={(e) => setProviderForm({ ...providerForm, api_key_env: e.target.value })}
              />
            </Field>
          </div>
          <Field label="API Key（留空则自动读取上方环境变量）">
            <Input
              type="password"
              className="font-mono"
              value={providerForm.api_key_inline}
              onChange={(e) => setProviderForm({ ...providerForm, api_key_inline: e.target.value })}
              placeholder="sk-..."
            />
          </Field>
          <div className="flex items-center justify-between rounded-[10px] border border-[var(--border)] bg-[var(--surface-subtle)] px-3 py-2.5">
            <div>
              <div className="text-xs font-medium">设为对话主理人（Coordinator）默认模型</div>
              <div className="text-[11px] text-[var(--muted)]">
                开启后对话工作台自动进入完整 ReAct 工具规划模式
              </div>
            </div>
            <Switch
              checked={providerForm.is_coordinator_default}
              onChange={(v) => setProviderForm({ ...providerForm, is_coordinator_default: v })}
            />
          </div>
        </div>
      </Modal>
    </div>
  )
}
