import { useEffect, useState } from 'react'
import {
  Activity,
  Bot,
  CheckCircle2,
  KeyRound,
  Plus,
  RefreshCw,
  Trash2,
  Zap,
} from 'lucide-react'
import { api, CAPABILITY_LABELS } from '../api'

interface Props {
  toast: (msg: string) => void
  onRefresh: () => Promise<void>
}

const ALL_CAPS = Object.keys(CAPABILITY_LABELS)

export default function AgentHub({ toast, onRefresh }: Props) {
  const [subTab, setSubTab] = useState<'agents' | 'providers' | 'custom' | 'doctor'>('agents')
  const [profiles, setProfiles] = useState<any[]>([])
  const [providers, setProviders] = useState<any[]>([])
  const [presets, setPresets] = useState<any[]>([])
  const [doctor, setDoctor] = useState<any[]>([])

  const [newProv, setNewProv] = useState({
    id: 'deepseek',
    name: 'DeepSeek 官方 API',
    preset: 'deepseek',
    base_url: 'https://api.deepseek.com/v1',
    api_key_env: 'DEEPSEEK_API_KEY',
    api_key_inline: '',
    default_model: 'deepseek-chat',
    is_coordinator_default: true,
    enabled: true,
  })

  const [customForm, setCustomForm] = useState({
    name: '',
    display_name: '',
    command_template: '',
    preferred_backend: 'local',
    description: '',
  })

  const loadAll = async () => {
    try {
      const [pRes, provRes, docRes] = await Promise.all([
        api<any>('/api/agents/profiles'),
        api<any>('/api/providers'),
        api<any>('/api/doctor'),
      ])
      setProfiles(pRes.profiles || [])
      setProviders(provRes.providers || [])
      setPresets(provRes.presets || [])
      setDoctor(docRes.checks || [])
    } catch (e: any) {
      toast('加载 Agent 中心失败: ' + e.message)
    }
  }

  useEffect(() => {
    loadAll()
  }, [])

  const updateProfile = async (name: string, patch: Record<string, any>) => {
    try {
      await api(`/api/agents/profiles/${encodeURIComponent(name)}`, 'POST', patch)
      await loadAll()
      await onRefresh()
      toast(`已更新 ${name} 档案`)
    } catch (e: any) {
      toast('更新失败: ' + e.message)
    }
  }

  const saveProvider = async () => {
    try {
      await api('/api/providers', 'POST', newProv)
      toast(`已保存 Provider：${newProv.name}`)
      await loadAll()
      await onRefresh()
    } catch (e: any) {
      toast('保存 Provider 失败: ' + e.message)
    }
  }

  const testProvider = async (id: string) => {
    try {
      const res = await api<{ ok: boolean; detail: string }>(`/api/providers/${encodeURIComponent(id)}/test`, 'POST')
      toast((res.ok ? '测连成功：' : '测连失败：') + res.detail)
    } catch (e: any) {
      toast('测连出错: ' + e.message)
    }
  }

  const deleteProvider = async (id: string) => {
    await api(`/api/providers/${encodeURIComponent(id)}`, 'DELETE')
    toast('已删除 Provider')
    await loadAll()
  }

  const addCustomAgent = async () => {
    try {
      await api('/api/agents/custom', 'POST', customForm)
      toast(`已注册自定义 Agent：${customForm.name}`)
      setCustomForm({ name: '', display_name: '', command_template: '', preferred_backend: 'local', description: '' })
      setSubTab('agents')
      await loadAll()
      await onRefresh()
    } catch (e: any) {
      toast('注册失败: ' + e.message)
    }
  }

  return (
    <div className="flex h-full flex-col overflow-hidden bg-[var(--bg)]">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--border)] bg-[var(--surface)] px-6 py-4">
        <div>
          <h1 className="text-lg font-bold">Agent 能力中心（Dimo 风格原生探测 · 只读不篡改）</h1>
          <p className="text-xs text-[var(--muted)]">
            自动识别电脑及 Ubuntu/WSL2 已装 Agent 与原生配置路径，维护能力强项画像，供 Coordinator 与编排画布按强项派活
          </p>
        </div>
        <button
          onClick={loadAll}
          className="flex items-center gap-1.5 rounded-xl border border-[var(--border)] bg-[var(--surface-2)] px-3 py-1.5 text-xs hover:border-sky-400"
        >
          <RefreshCw className="h-3.5 w-3.5" /> 重新扫描
        </button>
      </div>

      <div className="flex gap-2 border-b border-[var(--border)] bg-[var(--surface)] px-6 py-2 text-xs">
        {[
          ['agents', '已探测 Agent 与能力档案', Bot],
          ['providers', 'API Providers（Coordinator & 批扫）', KeyRound],
          ['custom', '接入自定义 CLI Agent', Plus],
          ['doctor', '体检报告 (Doctor)', Activity],
        ].map(([id, lbl, Icon]: any) => (
          <button
            key={id}
            onClick={() => setSubTab(id)}
            className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 font-medium transition ${
              subTab === id
                ? 'bg-sky-500/15 text-sky-400'
                : 'text-[var(--muted)] hover:bg-[var(--surface-2)] hover:text-[var(--fg)]'
            }`}
          >
            <Icon className="h-3.5 w-3.5" /> {lbl}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-y-auto p-6">
        {subTab === 'agents' && (
          <div className="grid gap-4 md:grid-cols-2">
            {profiles.map((p) => (
              <div
                key={p.name}
                className="flex flex-col justify-between rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4"
              >
                <div>
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <div className="flex items-center gap-2">
                        <strong className="text-sm">{p.display_name}</strong>
                        <span
                          className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${
                            p.detected
                              ? 'bg-emerald-500/20 text-emerald-400'
                              : 'bg-amber-500/20 text-amber-400'
                          }`}
                        >
                          {p.detected ? '本机已就绪' : '未在本机发现 / 远端'}
                        </span>
                      </div>
                      <div className="mt-0.5 font-mono text-[11px] text-[var(--muted)]">
                        {p.name} · {p.vendor} · 成本档位：{p.cost_tier}
                      </div>
                    </div>
                    <label className="flex cursor-pointer items-center gap-1.5 text-xs">
                      <input
                        type="checkbox"
                        checked={p.enabled}
                        onChange={(e) => updateProfile(p.name, { enabled: e.target.checked })}
                      />
                      <span>启用</span>
                    </label>
                  </div>

                  <p className="mt-2 text-xs text-[var(--muted)]">{p.description}</p>

                  <div className="mt-2.5 rounded-lg bg-[var(--surface-2)] px-3 py-2 font-mono text-[11px] text-[var(--muted)]">
                    <div>状态：{p.status_detail}</div>
                    {p.native_config_path && <div>原生配置（只读）：{p.native_config_path}</div>}
                  </div>

                  <div className="mt-3">
                    <div className="mb-1.5 text-[11px] font-semibold text-[var(--muted)]">
                      强项能力标签（点击切换）
                    </div>
                    <div className="flex flex-wrap gap-1.5">
                      {ALL_CAPS.map((cap) => {
                        const on = (p.capabilities || []).includes(cap)
                        return (
                          <button
                            key={cap}
                            onClick={() => {
                              const set = new Set(p.capabilities || [])
                              if (on) set.delete(cap)
                              else set.add(cap)
                              updateProfile(p.name, { capabilities: Array.from(set) })
                            }}
                            className={`rounded-full border px-2.5 py-0.5 text-[11px] transition ${
                              on
                                ? 'border-sky-500/50 bg-sky-500/15 text-sky-400'
                                : 'border-[var(--border)] text-[var(--muted)] hover:border-sky-500/30'
                            }`}
                          >
                            {CAPABILITY_LABELS[cap]}
                            {p.capability_scores?.[cap] ? ` · ${p.capability_scores[cap]}` : ''}
                          </button>
                        )
                      })}
                    </div>
                  </div>
                </div>

                <div className="mt-3 flex items-center justify-between border-t border-[var(--border)] pt-3 text-xs">
                  <span className="text-[var(--muted)]">首选运行主机</span>
                  <select
                    value={p.preferred_backend}
                    onChange={(e) => updateProfile(p.name, { preferred_backend: e.target.value })}
                    className="rounded-md border border-[var(--border)] bg-[var(--bg)] px-2 py-1 text-xs"
                  >
                    <option value="local">local（本机 Windows）</option>
                    <option value="ssh-ubuntu">ssh-ubuntu（Ubuntu2404）</option>
                    <option value="wsl2">wsl2（本机 WSL2）</option>
                  </select>
                </div>
              </div>
            ))}
          </div>
        )}

        {subTab === 'providers' && (
          <div className="grid gap-5 lg:grid-cols-2">
            <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-5">
              <h2 className="text-sm font-bold">添加 / 编辑 API Provider（驱动 Coordinator 与批量初筛）</h2>
              <div className="mt-3 flex flex-wrap gap-1.5">
                {presets.map((pr) => (
                  <button
                    key={pr.preset}
                    onClick={() =>
                      setNewProv({
                        ...newProv,
                        id: pr.preset,
                        name: pr.name,
                        preset: pr.preset,
                        base_url: pr.base_url,
                        api_key_env: pr.api_key_env,
                        default_model: pr.default_model,
                      })
                    }
                    className="rounded-full border border-[var(--border)] bg-[var(--surface-2)] px-3 py-1 text-xs hover:border-sky-400"
                  >
                    {pr.name}
                  </button>
                ))}
              </div>
              <div className="mt-4 space-y-3 text-xs">
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="mb-1 block font-semibold">ID</label>
                    <input
                      value={newProv.id}
                      onChange={(e) => setNewProv({ ...newProv, id: e.target.value })}
                      className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2"
                    />
                  </div>
                  <div>
                    <label className="mb-1 block font-semibold">显示名称</label>
                    <input
                      value={newProv.name}
                      onChange={(e) => setNewProv({ ...newProv, name: e.target.value })}
                      className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2"
                    />
                  </div>
                </div>
                <div>
                  <label className="mb-1 block font-semibold">Base URL（OpenAI 兼容端点）</label>
                  <input
                    value={newProv.base_url}
                    onChange={(e) => setNewProv({ ...newProv, base_url: e.target.value })}
                    className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 font-mono"
                  />
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="mb-1 block font-semibold">默认模型</label>
                    <input
                      value={newProv.default_model}
                      onChange={(e) => setNewProv({ ...newProv, default_model: e.target.value })}
                      className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 font-mono"
                    />
                  </div>
                  <div>
                    <label className="mb-1 block font-semibold">环境变量名（推荐）</label>
                    <input
                      value={newProv.api_key_env}
                      onChange={(e) => setNewProv({ ...newProv, api_key_env: e.target.value })}
                      className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 font-mono"
                    />
                  </div>
                </div>
                <div>
                  <label className="mb-1 block font-semibold">
                    或直接填写 API Key（仅存本机 config/providers.yaml，已 gitignore）
                  </label>
                  <input
                    type="password"
                    value={newProv.api_key_inline}
                    onChange={(e) => setNewProv({ ...newProv, api_key_inline: e.target.value })}
                    placeholder="sk-..."
                    className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 font-mono"
                  />
                </div>
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={newProv.is_coordinator_default}
                    onChange={(e) => setNewProv({ ...newProv, is_coordinator_default: e.target.checked })}
                  />
                  <span>设为「主对话框 Coordinator」默认推理大脑</span>
                </label>
                <button
                  onClick={saveProvider}
                  className="rounded-xl bg-sky-500 px-4 py-2 font-semibold text-white hover:bg-sky-400"
                >
                  保存 Provider
                </button>
              </div>
            </div>

            <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-5">
              <h2 className="text-sm font-bold">已配置 Providers（{providers.length}）</h2>
              <div className="mt-3 space-y-2.5">
                {providers.length === 0 ? (
                  <p className="text-xs text-[var(--muted)]">
                    尚未保存 Provider。在左侧点击预设（如 DeepSeek 官方 API）并填入 Key 即可开启完整 ReAct 对话调度。
                  </p>
                ) : (
                  providers.map((p) => (
                    <div
                      key={p.id}
                      className="flex items-center justify-between rounded-xl border border-[var(--border)] bg-[var(--surface-2)] p-3 text-xs"
                    >
                      <div>
                        <div className="flex items-center gap-2 font-semibold">
                          {p.name}
                          {p.is_coordinator_default && (
                            <span className="rounded-full bg-sky-500/20 px-2 py-0.5 text-[10px] text-sky-400">
                              Coordinator 默认
                            </span>
                          )}
                        </div>
                        <div className="mt-0.5 font-mono text-[11px] text-[var(--muted)]">
                          {p.default_model} · {p.base_url}
                        </div>
                      </div>
                      <div className="flex gap-1.5">
                        <button
                          onClick={() => testProvider(p.id)}
                          className="flex items-center gap-1 rounded-lg border border-[var(--border)] bg-[var(--surface)] px-2.5 py-1 hover:border-sky-400"
                        >
                          <Zap className="h-3 w-3 text-amber-400" /> 测连
                        </button>
                        <button
                          onClick={() => deleteProvider(p.id)}
                          className="rounded-lg border border-rose-500/30 p-1 text-rose-400 hover:bg-rose-500/15"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>
        )}

        {subTab === 'custom' && (
          <div className="max-w-xl rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-5 text-xs">
            <h2 className="text-sm font-bold">零代码接入任意本机/远端 CLI Agent</h2>
            <p className="mt-1 text-[var(--muted)]">
              支持变量占位符：<code>{'{skill_path}'}</code>、<code>{'{workspace_dir}'}</code>、
              <code>{'{output_file}'}</code>、<code>{'{prompt_file}'}</code>、<code>{'{stage}'}</code>
            </p>
            <div className="mt-4 space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="mb-1 block font-semibold">唯一标识（如 my-kimi-cli）</label>
                  <input
                    value={customForm.name}
                    onChange={(e) => setCustomForm({ ...customForm, name: e.target.value })}
                    className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2"
                  />
                </div>
                <div>
                  <label className="mb-1 block font-semibold">显示名称</label>
                  <input
                    value={customForm.display_name}
                    onChange={(e) => setCustomForm({ ...customForm, display_name: e.target.value })}
                    className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2"
                  />
                </div>
              </div>
              <div>
                <label className="mb-1 block font-semibold">命令模板</label>
                <input
                  value={customForm.command_template}
                  onChange={(e) => setCustomForm({ ...customForm, command_template: e.target.value })}
                  placeholder="my-agent run --prompt {prompt_file} --out {output_file}"
                  className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 font-mono"
                />
              </div>
              <div>
                <label className="mb-1 block font-semibold">简介与强项说明</label>
                <input
                  value={customForm.description}
                  onChange={(e) => setCustomForm({ ...customForm, description: e.target.value })}
                  className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2"
                />
              </div>
              <button
                onClick={addCustomAgent}
                className="rounded-xl bg-sky-500 px-4 py-2 font-semibold text-white hover:bg-sky-400"
              >
                注册并启用 Agent
              </button>
            </div>
          </div>
        )}

        {subTab === 'doctor' && (
          <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-5">
            <h2 className="mb-3 text-sm font-bold">当前流水线组件实时体检（auditflow doctor）</h2>
            <div className="space-y-2 text-xs">
              {doctor.map((r, i) => (
                <div
                  key={i}
                  className="flex items-center justify-between rounded-xl border border-[var(--border)] bg-[var(--surface-2)] px-4 py-2.5"
                >
                  <div className="flex items-center gap-2.5">
                    <CheckCircle2 className={`h-4 w-4 ${r.ok ? 'text-emerald-400' : 'text-amber-400'}`} />
                    <span className="font-mono font-semibold">{r.name}</span>
                    <span className="rounded bg-[var(--surface)] px-1.5 py-0.5 text-[10px] text-[var(--muted)]">
                      {r.kind}
                    </span>
                  </div>
                  <span className="text-[var(--muted)]">{r.detail}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
