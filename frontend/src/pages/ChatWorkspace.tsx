import { useEffect, useRef, useState } from 'react'
import {
  Bot,
  CheckCircle2,
  ChevronRight,
  Copy,
  Download,
  FileText,
  FolderGit2,
  Image as ImageIcon,
  Plus,
  RefreshCw,
  Send,
  ShieldAlert,
  Sparkles,
  Terminal,
  Trash2,
  XCircle,
} from 'lucide-react'
import { api, renderMarkdown, streamChatMessage } from '../api'

interface Props {
  overview: any
  onRefresh: () => Promise<void>
  toast: (msg: string) => void
}

const STARTER_PROMPTS = [
  '帮我在 GitHub 找 5 个 AI Agent / RAG 开源 Web 项目',
  '按本机已有 Agent 的强项，帮我推荐一套异构分工方案',
  '查看当前工作区全部目标和候选漏洞状态',
]

export default function ChatWorkspace({ overview, onRefresh, toast }: Props) {
  const [sessions, setSessions] = useState<any[]>([])
  const [activeSession, setActiveSession] = useState<string>('')
  const [messages, setMessages] = useState<any[]>([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [liveStatus, setLiveStatus] = useState<string | null>(null)
  const [liveEvents, setLiveEvents] = useState<any[]>([])
  const [actor, setActor] = useState('reviewer')

  const [selectedCand, setSelectedCand] = useState<{ target: string; candidate: string } | null>(null)
  const [candDetail, setCandDetail] = useState<any>(null)
  const [drawerTab, setDrawerTab] = useState<'cnvd' | 'evidence' | 'raw'>('cnvd')
  const [lightbox, setLightbox] = useState<string | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)

  const loadSessions = async () => {
    try {
      const res = await api<{ sessions: any[] }>('/api/chat/sessions')
      setSessions(res.sessions)
      if (!activeSession && res.sessions.length) {
        setActiveSession(res.sessions[0].session_id)
      }
    } catch (e: any) {
      toast('加载会话失败: ' + e.message)
    }
  }

  const loadMessages = async (sid: string) => {
    if (!sid) return
    try {
      const res = await api<{ messages: any[] }>(`/api/chat/sessions/${encodeURIComponent(sid)}/messages`)
      setMessages(res.messages)
    } catch (e: any) {
      toast('加载消息失败: ' + e.message)
    }
  }

  const openCandidate = async (target: string, candidate: string) => {
    setSelectedCand({ target, candidate })
    try {
      const d = await api(`/api/candidate/${encodeURIComponent(target)}/${encodeURIComponent(candidate)}`)
      setCandDetail(d)
    } catch (e: any) {
      toast('加载候选详情失败: ' + e.message)
    }
  }

  useEffect(() => {
    loadSessions()
  }, [])

  useEffect(() => {
    if (activeSession) loadMessages(activeSession)
  }, [activeSession])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, liveEvents, liveStatus])

  const createSession = async () => {
    const res = await api<{ session: any }>('/api/chat/sessions', 'POST', { title: '新审计会话' })
    setSessions((prev) => [res.session, ...prev])
    setActiveSession(res.session.session_id)
    setMessages([])
  }

  const deleteSession = async (sid: string) => {
    await api(`/api/chat/sessions/${encodeURIComponent(sid)}`, 'DELETE')
    const rest = sessions.filter((s) => s.session_id !== sid)
    setSessions(rest)
    if (activeSession === sid) {
      setActiveSession(rest[0]?.session_id || '')
    }
  }

  const sendMessage = async (textOverride?: string) => {
    const text = (textOverride ?? input).trim()
    if (!text || !activeSession || sending) return
    setInput('')
    setSending(true)
    setLiveStatus('Coordinator 正在响应...')
    setLiveEvents([])
    setMessages((prev) => [...prev, { msg_id: Date.now(), role: 'user', content: text, events: [] }])
    try {
      await streamChatMessage(activeSession, text, (ev) => {
        if (ev.type === 'status') {
          setLiveStatus(ev.message)
        } else if (ev.type === 'tool_call' || ev.type === 'tool_result' || ev.type === 'tool_error') {
          setLiveEvents((prev) => [...prev, ev])
        } else if (ev.type === 'message') {
          setMessages((prev) => [...prev, ev.message])
          setLiveEvents([])
          setLiveStatus(null)
        }
      })
      await loadSessions()
      await onRefresh()
    } catch (e: any) {
      toast('发送失败: ' + e.message)
    } finally {
      setSending(false)
      setLiveStatus(null)
    }
  }

  const decideInline = async (target: string, candidate: string | null, approve: boolean, autoClone = false) => {
    try {
      await api('/api/decide', 'POST', { target, candidate, approve, actor, auto_clone: autoClone })
      toast(approve ? `已批准 ${candidate || target}` : `已跳过 ${candidate || target}`)
      await onRefresh()
      if (selectedCand) openCandidate(selectedCand.target, selectedCand.candidate)
    } catch (e: any) {
      toast('审批操作失败: ' + e.message)
    }
  }

  const runStageAction = async (stage: string, target: string, candidate?: string) => {
    try {
      toast(`正在执行 ${stage}...`)
      const res = await api<any>('/api/stage', 'POST', { stage, target, candidate })
      toast(res.accepted ? `阶段 ${stage} 已完成` : `阶段 ${stage} 已生成交接包，请查看 logs/`)
      await onRefresh()
      if (candidate) openCandidate(target, candidate)
    } catch (e: any) {
      toast(`执行 ${stage} 失败: ` + e.message)
    }
  }

  const copyText = (text: string) => {
    navigator.clipboard.writeText(text).then(() => toast('已复制到剪贴板'))
  }

  const agents = (overview?.agent_profiles || []).filter((a: any) => a.enabled)
  const targets = overview?.targets || []

  return (
    <div className="grid h-full grid-cols-[260px_1fr_360px] overflow-hidden">
      {/* Column 1: Sessions + Projects Tree + Team Roster */}
      <div className="flex flex-col overflow-hidden border-r border-[var(--border)] bg-[var(--surface)]">
        <div className="flex items-center justify-between border-b border-[var(--border)] px-3 py-3">
          <span className="text-xs font-semibold uppercase tracking-wider text-[var(--muted)]">对话会话</span>
          <button
            onClick={createSession}
            className="flex items-center gap-1 rounded-md bg-sky-500/15 px-2 py-1 text-xs font-medium text-sky-400 hover:bg-sky-500/25"
          >
            <Plus className="h-3.5 w-3.5" /> 新会话
          </button>
        </div>
        <div className="max-h-44 space-y-1 overflow-y-auto p-2">
          {sessions.map((s) => (
            <div
              key={s.session_id}
              onClick={() => setActiveSession(s.session_id)}
              className={`group flex cursor-pointer items-center justify-between rounded-lg px-2.5 py-1.5 text-xs ${
                activeSession === s.session_id
                  ? 'bg-sky-500/15 font-medium text-sky-400'
                  : 'text-[var(--muted)] hover:bg-[var(--surface-2)] hover:text-[var(--fg)]'
              }`}
            >
              <span className="truncate">{s.title}</span>
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  deleteSession(s.session_id)
                }}
                className="opacity-0 hover:text-rose-400 group-hover:opacity-100"
              >
                <Trash2 className="h-3 w-3" />
              </button>
            </div>
          ))}
        </div>

        {/* Projects & Candidates */}
        <div className="flex items-center justify-between border-y border-[var(--border)] px-3 py-2.5">
          <span className="text-xs font-semibold uppercase tracking-wider text-[var(--muted)]">
            目标与候选 ({targets.length})
          </span>
          <button onClick={onRefresh} className="text-[var(--muted)] hover:text-[var(--fg)]">
            <RefreshCw className="h-3.5 w-3.5" />
          </button>
        </div>
        <div className="flex-1 space-y-2 overflow-y-auto p-2">
          {targets.length === 0 ? (
            <div className="p-3 text-center text-xs text-[var(--muted)]">
              在右侧对话框说一句“帮我找 5 个 AI 项目”或直接贴 GitHub 链接即可开始
            </div>
          ) : (
            targets.map((t: any) => (
              <div key={t.target_id} className="rounded-lg border border-[var(--border)] bg-[var(--surface-2)] p-2">
                <div className="flex items-center justify-between gap-1">
                  <span className="flex items-center gap-1.5 truncate text-xs font-semibold">
                    <FolderGit2 className="h-3.5 w-3.5 shrink-0 text-sky-400" />
                    {t.meta?.product || t.target_id}
                  </span>
                  <span className="rounded bg-slate-700/60 px-1.5 py-0.5 text-[10px] text-slate-200">
                    {t.status}
                  </span>
                </div>
                {t.status === 'GATE1_PENDING' && (
                  <div className="mt-1.5 flex gap-1">
                    <button
                      onClick={() => decideInline(t.target_id, null, true, true)}
                      className="flex-1 rounded bg-emerald-600/80 py-0.5 text-[11px] text-white hover:bg-emerald-600"
                    >
                      批准并克隆
                    </button>
                    <button
                      onClick={() => decideInline(t.target_id, null, false)}
                      className="rounded bg-rose-600/70 px-2 py-0.5 text-[11px] text-white hover:bg-rose-600"
                    >
                      跳过
                    </button>
                  </div>
                )}
                {(t.candidates || []).map((c: any) => (
                  <button
                    key={c.candidate_id}
                    onClick={() => openCandidate(t.target_id, c.candidate_id)}
                    className={`mt-1.5 flex w-full items-center justify-between rounded-md px-2 py-1 text-left text-[11px] transition ${
                      selectedCand?.target === t.target_id && selectedCand?.candidate === c.candidate_id
                        ? 'bg-sky-500/20 text-sky-300'
                        : 'bg-[var(--surface)] text-[var(--muted)] hover:text-[var(--fg)]'
                    }`}
                  >
                    <span className="truncate">
                      {c.candidate_id} · {c.title}
                    </span>
                    <ChevronRight className="h-3 w-3 shrink-0" />
                  </button>
                ))}
              </div>
            ))
          )}
        </div>

        {/* Team Roster (@Agent quick mention) */}
        <div className="border-t border-[var(--border)] p-2.5">
          <div className="mb-1.5 text-[11px] font-semibold text-[var(--muted)]">团队 Agent（点击 @ 点名）</div>
          <div className="flex flex-wrap gap-1">
            {agents.map((a: any) => (
              <button
                key={a.name}
                onClick={() => setInput((prev) => `${prev}${prev ? ' ' : ''}@${a.name} `)}
                className="flex items-center gap-1 rounded-full border border-[var(--border)] bg-[var(--surface-2)] px-2 py-0.5 text-[11px] hover:border-sky-400 hover:text-sky-400"
                title={a.description}
              >
                <span className={`h-1.5 w-1.5 rounded-full ${a.detected ? 'bg-emerald-400' : 'bg-amber-400'}`} />
                @{a.name}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Column 2: Main Conversational Coordinator Stream */}
      <div className="flex flex-col overflow-hidden bg-[var(--bg)]">
        <div className="flex items-center justify-between border-b border-[var(--border)] bg-[var(--surface)] px-5 py-3">
          <div className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-sky-400" />
            <span className="text-sm font-semibold">主控对话调度器（Coordinator）</span>
            <span className="rounded-full bg-sky-500/15 px-2 py-0.5 text-[11px] text-sky-400">
              支持 @Agent 委派 · 内联审批
            </span>
          </div>
          <div className="flex items-center gap-2 text-xs">
            <span className="text-[var(--muted)]">审批署名</span>
            <input
              value={actor}
              onChange={(e) => setActor(e.target.value)}
              className="w-24 rounded-md border border-[var(--border)] bg-[var(--bg)] px-2 py-1 text-xs"
            />
          </div>
        </div>

        <div className="flex-1 space-y-4 overflow-y-auto px-6 py-5">
          {messages.length === 0 && (
            <div className="mx-auto mt-10 max-w-xl text-center">
              <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-2xl bg-sky-500/15 text-sky-400">
                <Bot className="h-6 w-6" />
              </div>
              <h2 className="text-lg font-semibold">直接告诉我你要审计的目标或方向</h2>
              <p className="mt-1 text-xs text-[var(--muted)]">
                我会根据你电脑上已有 Agent 的能力强项自动分工（侦察 / 主审 / 异构复核 / 容器验证 / CNVD 成稿），关键审批会直接以卡片弹在对话流里。
              </p>
              <div className="mt-5 grid gap-2 text-left">
                {STARTER_PROMPTS.map((p) => (
                  <button
                    key={p}
                    onClick={() => sendMessage(p)}
                    className="rounded-xl border border-[var(--border)] bg-[var(--surface)] px-4 py-2.5 text-xs hover:border-sky-500/50 hover:bg-[var(--surface-2)]"
                  >
                    {p}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((m) => (
            <div key={m.msg_id} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              <div
                className={`max-w-[85%] rounded-2xl px-4 py-3 text-sm ${
                  m.role === 'user'
                    ? 'bg-sky-600 text-white'
                    : 'border border-[var(--border)] bg-[var(--surface)]'
                }`}
              >
                {m.role !== 'user' && (
                  <div className="mb-1.5 flex items-center gap-1.5 text-[11px] font-semibold text-sky-400">
                    <Bot className="h-3.5 w-3.5" />
                    {m.agent_name || 'Coordinator'}
                  </div>
                )}

                {(m.events || []).length > 0 && (
                  <details className="mb-2 rounded-lg border border-[var(--border)] bg-[var(--surface-2)] px-3 py-1.5 text-xs">
                    <summary className="cursor-pointer font-medium text-[var(--muted)]">
                      查看工具与 Agent 执行轨迹（{m.events.length} 步）
                    </summary>
                    <div className="mt-2 space-y-1.5 font-mono text-[11px]">
                      {m.events.map((ev: any, idx: number) => (
                        <div key={idx} className="rounded bg-[var(--bg)] p-2">
                          <span className="font-semibold text-sky-400">[{ev.type}]</span> {ev.tool}{' '}
                          {ev.args ? JSON.stringify(ev.args) : ''}
                          {ev.error ? <span className="text-rose-400"> {ev.error}</span> : null}
                        </div>
                      ))}
                    </div>
                  </details>
                )}

                <div
                  className="md-prose text-sm"
                  dangerouslySetInnerHTML={{ __html: renderMarkdown(m.content) }}
                />

                {/* Inline Interactive Gate Card */}
                {m.gate_card && (
                  <div className="mt-3 rounded-xl border border-amber-500/40 bg-amber-500/10 p-3">
                    <div className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-amber-400">
                      <ShieldAlert className="h-4 w-4" />
                      {m.gate_card.title}
                    </div>
                    <div className="space-y-2">
                      {(m.gate_card.items || []).map((item: any, idx: number) => (
                        <div
                          key={idx}
                          className="flex items-center justify-between gap-2 rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-xs"
                        >
                          <div className="min-w-0">
                            <div className="truncate font-semibold">
                              {item.product || item.candidate_id}
                              {item.stars != null ? ` · ★ ${item.stars}` : ''}
                            </div>
                            <div className="truncate text-[11px] text-[var(--muted)]">
                              {item.repo_url || item.status}
                            </div>
                          </div>
                          <div className="flex shrink-0 gap-1.5">
                            {m.gate_card.kind === 'gate1' ? (
                              <>
                                <button
                                  onClick={() => decideInline(item.target_id, null, true, true)}
                                  className="flex items-center gap-1 rounded-md bg-emerald-600 px-2.5 py-1 text-[11px] font-medium text-white hover:bg-emerald-500"
                                >
                                  <CheckCircle2 className="h-3 w-3" /> 通过并克隆
                                </button>
                                <button
                                  onClick={() => decideInline(item.target_id, null, false)}
                                  className="flex items-center gap-1 rounded-md bg-rose-600/80 px-2 py-1 text-[11px] text-white hover:bg-rose-600"
                                >
                                  <XCircle className="h-3 w-3" /> 跳过
                                </button>
                              </>
                            ) : (
                              <>
                                <button
                                  onClick={() => decideInline(m.gate_card.target_id, item.candidate_id, true)}
                                  className="rounded-md bg-emerald-600 px-2.5 py-1 text-[11px] font-medium text-white"
                                >
                                  批准验证
                                </button>
                                <button
                                  onClick={() => decideInline(m.gate_card.target_id, item.candidate_id, false)}
                                  className="rounded-md bg-rose-600/80 px-2 py-1 text-[11px] text-white"
                                >
                                  标误报
                                </button>
                              </>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          ))}

          {(liveStatus || liveEvents.length > 0) && (
            <div className="max-w-[85%] rounded-2xl border border-sky-500/30 bg-[var(--surface)] px-4 py-3 text-xs">
              <div className="flex items-center gap-2 text-sky-400">
                <Terminal className="h-3.5 w-3.5 animate-pulse" />
                {liveStatus || '执行中...'}
              </div>
              {liveEvents.map((ev, i) => (
                <div key={i} className="mt-1 font-mono text-[11px] text-[var(--muted)]">
                  [{ev.type}] {ev.tool}
                </div>
              ))}
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        {/* Bottom Composer */}
        <div className="border-t border-[var(--border)] bg-[var(--surface)] p-4">
          <div className="flex items-end gap-2 rounded-xl border border-[var(--border)] bg-[var(--bg)] p-2 focus-within:border-sky-500">
            <textarea
              rows={2}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  sendMessage()
                }
              }}
              placeholder="输入任务（例如：帮我在 GitHub 找 5 个 AI Agent 项目 / 粘贴仓库 URL / 用 @codex 验证...）Enter 发送，Shift+Enter 换行"
              className="flex-1 resize-none bg-transparent px-2 py-1 text-sm outline-none"
            />
            <button
              disabled={sending || !input.trim()}
              onClick={() => sendMessage()}
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-sky-500 text-white hover:bg-sky-400 disabled:opacity-40"
            >
              <Send className="h-4 w-4" />
            </button>
          </div>
        </div>
      </div>

      {/* Column 3: Right Inspector (Evidence Gallery + CNVD Form + Actions) */}
      <div className="flex flex-col overflow-hidden border-l border-[var(--border)] bg-[var(--surface)]">
        <div className="border-b border-[var(--border)] px-4 py-3">
          <div className="text-xs font-semibold uppercase tracking-wider text-[var(--muted)]">
            候选上下文与 CNVD 交付
          </div>
          {selectedCand && (
            <div className="mt-1 truncate text-xs font-medium text-sky-400">
              {selectedCand.target} / {selectedCand.candidate}
            </div>
          )}
        </div>

        {!candDetail ? (
          <div className="flex flex-1 flex-col items-center justify-center p-6 text-center text-xs text-[var(--muted)]">
            <FileText className="mb-2 h-8 w-8 opacity-40" />
            点击左侧任意候选漏洞，在此查看自动截图、一键复制 CNVD 表单与下载 `.docx` 报告
          </div>
        ) : (
          <>
            <div className="flex flex-wrap gap-1.5 border-b border-[var(--border)] p-3">
              <button
                onClick={() => runStageAction('verify', candDetail.target_id, candDetail.candidate_id)}
                className="rounded-md border border-[var(--border)] bg-[var(--surface-2)] px-2.5 py-1 text-xs hover:border-sky-400"
              >
                执行验证
              </button>
              <button
                onClick={() => runStageAction('evidence', candDetail.target_id, candDetail.candidate_id)}
                className="rounded-md border border-[var(--border)] bg-[var(--surface-2)] px-2.5 py-1 text-xs hover:border-sky-400"
              >
                生成截图
              </button>
              <button
                onClick={async () => {
                  try {
                    const res = await api<any>('/api/report', 'POST', {
                      target: candDetail.target_id,
                      candidate: candDetail.candidate_id,
                    })
                    toast('已生成报告：' + res.files[0])
                    openCandidate(candDetail.target_id, candDetail.candidate_id)
                    onRefresh()
                  } catch (e: any) {
                    toast('生成报告失败: ' + e.message)
                  }
                }}
                className="rounded-md bg-emerald-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-emerald-500"
              >
                生成 .docx + 表单
              </button>
              {candDetail.has_docx && (
                <a
                  href={`/api/download-docx/${encodeURIComponent(candDetail.target_id)}/${encodeURIComponent(candDetail.candidate_id)}`}
                  className="flex items-center gap-1 rounded-md bg-sky-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-sky-500"
                >
                  <Download className="h-3.5 w-3.5" /> 下载 .docx
                </a>
              )}
            </div>

            <div className="flex border-b border-[var(--border)] text-xs">
              {[
                ['cnvd', 'CNVD 表单'],
                ['evidence', `截图 (${candDetail.evidence_images?.length || 0})`],
                ['raw', 'JSON 事实'],
              ].map(([id, lbl]) => (
                <button
                  key={id}
                  onClick={() => setDrawerTab(id as any)}
                  className={`flex-1 py-2 font-medium ${
                    drawerTab === id
                      ? 'border-b-2 border-sky-400 text-sky-400'
                      : 'text-[var(--muted)] hover:text-[var(--fg)]'
                  }`}
                >
                  {lbl}
                </button>
              ))}
            </div>

            <div className="flex-1 overflow-y-auto p-3">
              {drawerTab === 'cnvd' && candDetail.cnvd_form && (
                <div className="space-y-2.5">
                  {[
                    ['漏洞名称', candDetail.cnvd_form.vuln_title],
                    ['涉及厂商', candDetail.cnvd_form.vendor],
                    ['受影响产品', candDetail.cnvd_form.product],
                    ['受影响版本', candDetail.cnvd_form.affected_versions],
                    ['项目地址', candDetail.cnvd_form.repo_url],
                    ['漏洞类型', `${candDetail.cnvd_form.vuln_category} (${candDetail.cnvd_form.cwe})`],
                    ['危害等级', candDetail.cnvd_form.severity],
                    ['漏洞描述', candDetail.cnvd_form.vuln_description],
                    ['漏洞危害', candDetail.cnvd_form.vuln_impact],
                    ['验证方式简述', candDetail.cnvd_form.repro_summary],
                    ['修复建议', candDetail.cnvd_form.remediation_suggestion],
                  ].map(([k, v]) => (
                    <div key={k} className="rounded-lg border border-[var(--border)] bg-[var(--surface-2)] p-2.5">
                      <div className="mb-1 flex items-center justify-between">
                        <span className="text-xs font-semibold">{k}</span>
                        <button
                          onClick={() => copyText(String(v || ''))}
                          className="flex items-center gap-1 rounded bg-[var(--surface)] px-1.5 py-0.5 text-[11px] text-sky-400 hover:bg-sky-500/15"
                        >
                          <Copy className="h-3 w-3" /> 复制
                        </button>
                      </div>
                      <div className="whitespace-pre-wrap break-words text-xs text-[var(--muted)]">
                        {v || '未提供'}
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {drawerTab === 'evidence' && (
                <div className="space-y-3">
                  {(candDetail.evidence_images || []).length === 0 ? (
                    <div className="py-8 text-center text-xs text-[var(--muted)]">
                      <ImageIcon className="mx-auto mb-2 h-7 w-7 opacity-40" />
                      暂无截图，点击上方「生成截图」即可自动渲染
                    </div>
                  ) : (
                    candDetail.evidence_images.map((img: any) => (
                      <div key={img.name} className="rounded-lg border border-[var(--border)] bg-[var(--surface-2)] p-2">
                        <div className="mb-1 text-[11px] text-[var(--muted)]">{img.name}</div>
                        <img
                          src={img.url}
                          alt={img.name}
                          onClick={() => setLightbox(img.url)}
                          className="w-full cursor-zoom-in rounded border border-[var(--border)] bg-white"
                        />
                      </div>
                    ))
                  )}
                </div>
              )}

              {drawerTab === 'raw' && (
                <pre className="whitespace-pre-wrap break-words rounded-lg bg-[var(--surface-2)] p-3 font-mono text-[11px]">
                  {JSON.stringify({ audit: candDetail.audit, deploy_log: candDetail.deploy_log, verify: candDetail.verify }, null, 2)}
                </pre>
              )}
            </div>
          </>
        )}
      </div>

      {lightbox && (
        <div
          onClick={() => setLightbox(null)}
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-8"
        >
          <img src={lightbox} className="max-h-full max-w-full rounded-xl shadow-2xl" />
        </div>
      )}
    </div>
  )
}
