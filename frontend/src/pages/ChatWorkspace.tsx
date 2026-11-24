import { useEffect, useRef, useState } from 'react'
import { marked } from 'marked'
import {
  ArrowUp,
  Check,
  ChevronDown,
  ChevronRight,
  Copy,
  Download,
  ExternalLink,
  FileText,
  FolderGit2,
  Image as ImageIcon,
  PanelRightClose,
  PanelRightOpen,
  Play,
  Plus,
  ShieldAlert,
  Sparkles,
  Trash2,
  Wrench,
  X,
} from 'lucide-react'
import { api, streamChatMessage } from '../api'
import { AgentIcon } from '../components/AgentIcon'
import { Button, SegmentedControl, StatusPill, cn } from '../components/ui'

interface Props {
  overview: any
  onRefresh: () => Promise<void>
  toast: (msg: string) => void
  dark: boolean
}

const QUICK_PROMPTS = [
  {
    title: '搜索 AI Agent 开源目标',
    desc: '按关键词检索 GitHub 并自动去重入库',
    text: '帮我在 GitHub 找 5 个 AI Agent / MCP 开源项目并准备 Gate 1 审批',
  },
  {
    title: '按 Agent 强项推荐分工',
    desc: '结合本机探测结果生成异构互审方案',
    text: '按当前电脑各 Agent 的能力强项，帮我推荐一套异构互审团队分配方案',
  },
  {
    title: '导入指定仓库开始审计',
    desc: '粘贴 GitHub / Gitee 链接直接创建工单',
    text: '帮我导入 https://github.com/IceWhaleTech/CasaOS 并发起 Gate 1 审批',
  },
  {
    title: '查看流水线进度与待办',
    desc: '汇总当前所有目标与待审批候选漏洞',
    text: '汇总当前工作区所有审计目标、候选漏洞状态与下一步建议',
  },
]

const STATUS_TONE: Record<string, 'neutral' | 'ok' | 'warn' | 'danger' | 'info'> = {
  DISCOVERED: 'neutral',
  GATE1_PENDING: 'warn',
  CLONED: 'info',
  MAPPED: 'info',
  AUDITED: 'info',
  GATE2_PENDING: 'warn',
  VERIFY_APPROVED: 'ok',
  VERIFIED: 'ok',
  EVIDENCE_READY: 'ok',
  REPORTED: 'ok',
  NEEDS_HUMAN_ENV: 'danger',
  REJECTED_FP: 'neutral',
}

export default function ChatWorkspace({ overview, onRefresh, toast, dark }: Props) {
  const [sessions, setSessions] = useState<any[]>([])
  const [activeId, setActiveId] = useState<string>('')
  const [messages, setMessages] = useState<any[]>([])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [liveStatus, setLiveStatus] = useState('')
  const [liveEvents, setLiveEvents] = useState<any[]>([])
  const [expandedTools, setExpandedTools] = useState<Record<number, boolean>>({})

  // Right drawer
  const [drawerOpen, setDrawerOpen] = useState(true)
  const [drawerTab, setDrawerTab] = useState<'targets' | 'evidence'>('targets')
  const [selectedCand, setSelectedCand] = useState<{ target: string; candidate: string } | null>(null)
  const [candDetail, setCandDetail] = useState<any>(null)
  const [lightboxImg, setLightboxImg] = useState<string | null>(null)

  const scrollRef = useRef<HTMLDivElement | null>(null)

  const loadSessions = async () => {
    try {
      const res = await api<any>('/api/chat/sessions')
      const list = res.sessions || []
      setSessions(list)
      if (!activeId && list.length > 0) {
        setActiveId(list[0].session_id)
      }
    } catch (e: any) {
      toast('加载会话失败: ' + e.message)
    }
  }

  const loadMessages = async (sid: string) => {
    if (!sid) return
    try {
      const res = await api<any>(`/api/chat/sessions/${encodeURIComponent(sid)}/messages`)
      setMessages(res.messages || [])
    } catch (e: any) {
      toast('加载历史消息失败: ' + e.message)
    }
  }

  useEffect(() => {
    loadSessions()
  }, [])

  useEffect(() => {
    if (activeId) loadMessages(activeId)
  }, [activeId])

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages, liveEvents, liveStatus])

  const createSession = async () => {
    const res = await api<any>('/api/chat/sessions', 'POST', { title: '新审计会话' })
    const s = res.session
    setSessions((prev) => [s, ...prev])
    setActiveId(s.session_id)
    setMessages([])
  }

  const deleteSession = async (sid: string) => {
    await api(`/api/chat/sessions/${encodeURIComponent(sid)}`, 'DELETE')
    const next = sessions.filter((s) => s.session_id !== sid)
    setSessions(next)
    if (activeId === sid) {
      if (next.length > 0) setActiveId(next[0].session_id)
      else await createSession()
    }
  }

  const sendMessage = async (overrideText?: string) => {
    const text = (overrideText ?? input).trim()
    if (!text || streaming || !activeId) return
    setInput('')
    setStreaming(true)
    setLiveStatus('Coordinator 正在规划与调用工具...')
    setLiveEvents([])

    const optimisticUser = {
      msg_id: Date.now(),
      role: 'user',
      content: text,
      events: [],
      gate_card: null,
    }
    setMessages((prev) => [...prev, optimisticUser])

    try {
      await streamChatMessage(activeId, text, (ev: any) => {
        if (ev.type === 'status') {
          setLiveStatus(ev.message || '')
        } else if (ev.type === 'tool_call' || ev.type === 'tool_result' || ev.type === 'tool_error') {
          setLiveEvents((prev) => [...prev, ev])
        } else if (ev.type === 'message' && ev.message) {
          setMessages((prev) => [...prev, ev.message])
          setLiveEvents([])
          setLiveStatus('')
        }
      })
      await loadSessions()
      await onRefresh()
    } catch (e: any) {
      toast('发送失败: ' + e.message)
    } finally {
      setStreaming(false)
      setLiveStatus('')
    }
  }

  const handleGateDecision = async (
    target: string,
    approve: boolean,
    candidate?: string,
    autoClone = false,
  ) => {
    try {
      await api('/api/decide', 'POST', {
        target,
        candidate,
        approve,
        auto_clone: autoClone,
        actor: 'reviewer',
      })
      toast(
        candidate
          ? `${candidate} 已${approve ? '放行进入隔离验证' : '标为误报排除'}`
          : `${target} 已${approve ? (autoClone ? '审批通过并克隆源码' : '审批通过') : '拒绝跳过'}`,
      )
      await onRefresh()
    } catch (e: any) {
      toast('审批操作失败: ' + e.message)
    }
  }

  const runStageQuick = async (stage: string, target: string, candidate?: string) => {
    try {
      toast(`正在执行 ${stage} (${target})...`)
      await api('/api/stage', 'POST', { stage, target, candidate })
      toast(`${stage} 执行完成`)
      await onRefresh()
    } catch (e: any) {
      toast(`${stage} 执行失败: ` + e.message)
    }
  }

  const openCandidateEvidence = async (target: string, candidate: string) => {
    setSelectedCand({ target, candidate })
    setDrawerOpen(true)
    setDrawerTab('evidence')
    try {
      const res = await api<any>(
        `/api/candidate/${encodeURIComponent(target)}/${encodeURIComponent(candidate)}`,
      )
      setCandDetail(res)
    } catch (e: any) {
      toast('读取候选详情失败: ' + e.message)
    }
  }

  const generateReport = async (target: string, candidate: string) => {
    try {
      await api('/api/report', 'POST', { target, candidate })
      toast('已生成 CNVD Word 报告与提报表单')
      await openCandidateEvidence(target, candidate)
      await onRefresh()
    } catch (e: any) {
      toast('生成报告失败: ' + e.message)
    }
  }

  const copyText = async (label: string, text: string) => {
    try {
      await navigator.clipboard.writeText(text)
      toast(`已复制：${label}`)
    } catch {
      toast('复制失败，请手动选中复制')
    }
  }

  const enabledAgents = (overview?.agent_profiles || []).filter((a: any) => a.enabled)
  const targets = overview?.targets || []

  return (
    <div className="flex h-full overflow-hidden">
      {/* Left Session Rail */}
      <div className="flex w-[220px] shrink-0 flex-col border-r border-[var(--border)] bg-[var(--surface-subtle)]">
        <div className="flex items-center justify-between border-b border-[var(--border)] px-3 py-3">
          <span className="text-xs font-semibold text-[var(--fg-secondary)]">审计会话</span>
          <Button size="sm" variant="secondary" onClick={createSession}>
            <Plus className="h-3.5 w-3.5" /> 新建
          </Button>
        </div>

        <div className="flex-1 space-y-0.5 overflow-y-auto p-2">
          {sessions.map((s) => {
            const active = s.session_id === activeId
            return (
              <div
                key={s.session_id}
                onClick={() => setActiveId(s.session_id)}
                className={cn(
                  'group flex items-center justify-between gap-2 rounded-[8px] px-2.5 py-2 text-xs transition-colors cursor-pointer',
                  active
                    ? 'bg-[var(--surface-active)] font-medium text-[var(--fg)]'
                    : 'text-[var(--muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--fg)]',
                )}
              >
                <span className="truncate">{s.title || '新审计会话'}</span>
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation()
                    deleteSession(s.session_id)
                  }}
                  className="opacity-0 transition-opacity group-hover:opacity-100 text-[var(--subtle)] hover:text-[var(--danger)] cursor-pointer"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            )
          })}
        </div>

        <div className="border-t border-[var(--border)] p-3 text-[11px] text-[var(--muted)]">
          <div className="flex items-center justify-between">
            <span>跟踪目标</span>
            <span className="font-semibold text-[var(--fg)]">{overview?.counts?.targets ?? 0}</span>
          </div>
          <div className="mt-1 flex items-center justify-between">
            <span>待过闸门</span>
            <span className="font-semibold text-[var(--warn)]">
              {(overview?.counts?.gate1_pending ?? 0) + (overview?.counts?.gate2_pending ?? 0)}
            </span>
          </div>
        </div>
      </div>

      {/* Center Conversation Column */}
      <div className="flex flex-1 flex-col overflow-hidden bg-[var(--surface)]">
        {/* Minimal Top Header */}
        <div className="flex h-12 shrink-0 items-center justify-between border-b border-[var(--border)] px-5">
          <div className="flex items-center gap-2.5">
            <AgentIcon agent="coordinator" dark={dark} size={20} />
            <span className="text-[13.5px] font-semibold">Coordinator 主理人</span>
            <span className="text-xs text-[var(--muted)]">·</span>
            <span className="text-xs text-[var(--muted)]">
              {enabledAgents.length} 个 Agent 待命
            </span>
          </div>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => setDrawerOpen((v) => !v)}
            title="切换右侧流水线与证据抽屉"
          >
            {drawerOpen ? (
              <PanelRightClose className="h-4 w-4" />
            ) : (
              <PanelRightOpen className="h-4 w-4" />
            )}
            <span>{drawerOpen ? '收起面板' : '流水线与证据'}</span>
          </Button>
        </div>

        {/* Messages Area */}
        <div ref={scrollRef} className="flex-1 overflow-y-auto px-6 py-6">
          <div className="mx-auto max-w-[740px] space-y-6">
            {messages.length === 0 && !streaming && (
              <div className="pt-10 pb-4">
                <div className="flex items-center gap-2.5">
                  <div className="flex h-9 w-9 items-center justify-center rounded-[10px] bg-[var(--primary)] text-[var(--primary-fg)]">
                    <Sparkles className="h-4 w-4" />
                  </div>
                  <div>
                    <h2 className="text-[18px] font-semibold tracking-[-0.02em]">
                      今天准备审计哪个开源项目？
                    </h2>
                    <p className="text-xs text-[var(--muted)]">
                      直接说出需求或粘贴仓库地址，我会自动调度不同强项的 Agent 并在关键闸门停下等你确认。
                    </p>
                  </div>
                </div>

                {/* Quick Prompt Grid (flat Tahoe inset cards) */}
                <div className="mt-6 grid gap-2.5 sm:grid-cols-2">
                  {QUICK_PROMPTS.map((q) => (
                    <button
                      key={q.title}
                      type="button"
                      onClick={() => sendMessage(q.text)}
                      className="tahoe-card p-3.5 text-left transition-colors hover:bg-[var(--surface-hover)] cursor-pointer"
                    >
                      <div className="text-[13px] font-medium text-[var(--fg)]">{q.title}</div>
                      <div className="mt-0.5 text-xs text-[var(--muted)]">{q.desc}</div>
                    </button>
                  ))}
                </div>
              </div>
            )}

            {messages.map((m) => {
              const isUser = m.role === 'user'
              const toolEvents = (m.events || []).filter(
                (e: any) => e.type === 'tool_call' || e.type === 'tool_result' || e.type === 'tool_error',
              )
              const toolsOpen = Boolean(expandedTools[m.msg_id])

              if (isUser) {
                return (
                  <div key={m.msg_id} className="flex justify-end">
                    <div className="max-w-[82%] rounded-[14px] bg-[var(--control-bg)] px-4 py-2.5 text-[13.5px] leading-relaxed text-[var(--fg)]">
                      {m.content}
                    </div>
                  </div>
                )
              }

              return (
                <div key={m.msg_id} className="flex items-start gap-3">
                  <div className="mt-0.5">
                    <AgentIcon agent="coordinator" dark={dark} size={22} />
                  </div>
                  <div className="min-w-0 flex-1 space-y-2.5">
                    <div className="flex items-center gap-2 text-xs">
                      <span className="font-semibold text-[var(--fg)]">
                        {m.agent_name || 'Coordinator'}
                      </span>
                      {toolEvents.length > 0 && (
                        <button
                          type="button"
                          onClick={() =>
                            setExpandedTools((prev) => ({ ...prev, [m.msg_id]: !prev[m.msg_id] }))
                          }
                          className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] text-[var(--muted)] hover:bg-[var(--control-bg)] hover:text-[var(--fg)] cursor-pointer"
                        >
                          <Wrench className="h-3 w-3" />
                          <span>调用了 {Math.ceil(toolEvents.length / 2)} 次工具</span>
                          {toolsOpen ? (
                            <ChevronDown className="h-3 w-3" />
                          ) : (
                            <ChevronRight className="h-3 w-3" />
                          )}
                        </button>
                      )}
                    </div>

                    {toolsOpen && toolEvents.length > 0 && (
                      <div className="rounded-[10px] border border-[var(--border)] bg-[var(--surface-subtle)] p-3 font-mono text-[11.5px] space-y-1.5">
                        {toolEvents.map((ev: any, idx: number) => (
                          <div key={idx} className="break-all text-[var(--fg-secondary)]">
                            <span className="font-semibold text-[var(--fg)]">{ev.tool}</span>{' '}
                            <span className="text-[var(--muted)]">
                              {ev.type === 'tool_call'
                                ? `← ${JSON.stringify(ev.args || {})}`
                                : ev.type === 'tool_error'
                                  ? `✕ ${ev.error}`
                                  : `→ ${JSON.stringify(ev.result || {}).slice(0, 220)}`}
                            </span>
                          </div>
                        ))}
                      </div>
                    )}

                    <div
                      className="md-prose"
                      dangerouslySetInnerHTML={{ __html: marked.parse(m.content || '') as string }}
                    />

                    {/* Inline Interactive Gate 1 / Gate 2 Card */}
                    {m.gate_card && (
                      <div className="tahoe-card overflow-hidden">
                        <div className="flex items-center justify-between border-b border-[var(--border)] bg-[var(--surface-subtle)] px-4 py-2.5">
                          <div className="flex items-center gap-2 text-xs font-semibold">
                            <ShieldAlert className="h-4 w-4 text-[var(--warn)]" />
                            <span>{m.gate_card.title}</span>
                          </div>
                          <StatusPill tone="warn" dot>
                            等待人工拍板
                          </StatusPill>
                        </div>
                        <div className="divide-y divide-[var(--border)]">
                          {(m.gate_card.items || []).map((item: any, idx: number) => (
                            <div
                              key={idx}
                              className="flex flex-wrap items-center justify-between gap-3 px-4 py-3"
                            >
                              <div className="min-w-0">
                                <div className="text-[13px] font-medium">
                                  {m.gate_card.kind === 'gate1'
                                    ? item.product || item.target_id
                                    : item.candidate_id}
                                </div>
                                <div className="mt-0.5 truncate font-mono text-[11px] text-[var(--muted)]">
                                  {m.gate_card.kind === 'gate1'
                                    ? `${item.target_id}${item.language ? ` · ${item.language}` : ''}${item.stars ? ` · ★${item.stars}` : ''}`
                                    : `当前状态：${item.status}`}
                                </div>
                              </div>
                              <div className="flex items-center gap-1.5">
                                {m.gate_card.kind === 'gate1' ? (
                                  <>
                                    <Button
                                      size="sm"
                                      variant="primary"
                                      onClick={() => handleGateDecision(item.target_id, true, undefined, true)}
                                    >
                                      <Check className="h-3.5 w-3.5" /> 通过并克隆
                                    </Button>
                                    <Button
                                      size="sm"
                                      variant="secondary"
                                      onClick={() => handleGateDecision(item.target_id, false)}
                                    >
                                      跳过
                                    </Button>
                                  </>
                                ) : (
                                  <>
                                    <Button
                                      size="sm"
                                      variant="primary"
                                      onClick={() =>
                                        handleGateDecision(m.gate_card.target_id, true, item.candidate_id)
                                      }
                                    >
                                      <Check className="h-3.5 w-3.5" /> 放行验证
                                    </Button>
                                    <Button
                                      size="sm"
                                      variant="secondary"
                                      onClick={() =>
                                        handleGateDecision(m.gate_card.target_id, false, item.candidate_id)
                                      }
                                    >
                                      标为误报
                                    </Button>
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
              )
            })}

            {/* Streaming Live Indicator */}
            {streaming && (
              <div className="flex items-start gap-3">
                <div className="mt-0.5">
                  <AgentIcon agent="coordinator" dark={dark} size={22} />
                </div>
                <div className="flex-1 space-y-2">
                  <div className="flex items-center gap-2 text-xs text-[var(--muted)]">
                    <span className="h-2 w-2 animate-pulse rounded-full bg-[var(--primary)]" />
                    <span>{liveStatus || '正在处理...'}</span>
                  </div>
                  {liveEvents.length > 0 && (
                    <div className="rounded-[10px] border border-[var(--border)] bg-[var(--surface-subtle)] p-2.5 font-mono text-[11px] space-y-1">
                      {liveEvents.map((ev, i) => (
                        <div key={i} className="truncate text-[var(--muted)]">
                          <span className="font-semibold text-[var(--fg)]">{ev.tool}</span>{' '}
                          {ev.type === 'tool_call' ? '运行中...' : '完成'}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Floating Tahoe Composer */}
        <div className="shrink-0 px-6 pb-4 pt-2">
          <div className="mx-auto max-w-[740px] rounded-[14px] border border-[var(--border-strong)] bg-[var(--surface)] shadow-[var(--shadow-sm)] transition-colors focus-within:border-[var(--primary)]">
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
              placeholder="输入指令、粘贴 GitHub/Gitee 链接，或输入 @Agent 点名委派任务（Enter 发送，Shift+Enter 换行）"
              className="w-full resize-none bg-transparent px-4 pt-3 pb-1 text-[13.5px] text-[var(--fg)] placeholder:text-[var(--subtle)] focus:shadow-none"
            />
            <div className="flex items-center justify-between gap-2 px-3 pb-2.5 pt-1">
              <div className="flex flex-wrap items-center gap-1">
                {enabledAgents.slice(0, 5).map((a: any) => (
                  <button
                    key={a.name}
                    type="button"
                    onClick={() => setInput((v) => `${v ? v + ' ' : ''}@${a.name} `)}
                    className="inline-flex h-6 items-center gap-1.5 rounded-full border border-[var(--border)] bg-[var(--surface-subtle)] px-2 text-[11px] text-[var(--fg-secondary)] hover:bg-[var(--surface-hover)] cursor-pointer"
                  >
                    <AgentIcon agent={a.name} dark={dark} size={12} />
                    <span>@{a.name}</span>
                  </button>
                ))}
              </div>
              <button
                type="button"
                disabled={streaming || !input.trim()}
                onClick={() => sendMessage()}
                className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-[var(--primary)] text-[var(--primary-fg)] transition-opacity hover:opacity-90 disabled:opacity-35 cursor-pointer"
              >
                <ArrowUp className="h-4 w-4" />
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Right Collapsible Pipeline & Evidence Drawer */}
      {drawerOpen && (
        <aside className="flex w-[340px] shrink-0 flex-col border-l border-[var(--border)] bg-[var(--surface-subtle)]">
          <div className="flex h-12 shrink-0 items-center justify-between border-b border-[var(--border)] px-3">
            <SegmentedControl
              value={drawerTab}
              onChange={setDrawerTab}
              options={[
                { value: 'targets', label: `目标 (${targets.length})` },
                { value: 'evidence', label: '证据 & CNVD' },
              ]}
            />
          </div>

          {drawerTab === 'targets' ? (
            <div className="flex-1 space-y-2.5 overflow-y-auto p-3">
              {targets.length === 0 ? (
                <div className="tahoe-card p-6 text-center text-xs text-[var(--muted)]">
                  <FolderGit2 className="mx-auto mb-2 h-6 w-6 text-[var(--subtle)]" />
                  暂无跟踪目标。在对话中说「帮我找 5 个 AI 项目」或粘贴仓库 URL 即可入库。
                </div>
              ) : (
                targets.map((t: any) => (
                  <div key={t.target_id} className="tahoe-card p-3 space-y-2">
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <div className="truncate text-[13px] font-semibold">
                          {t.product || t.target_id}
                        </div>
                        <div className="truncate font-mono text-[10.5px] text-[var(--muted)]">
                          {t.target_id}
                        </div>
                      </div>
                      <StatusPill tone={STATUS_TONE[t.status] || 'neutral'}>{t.status}</StatusPill>
                    </div>

                    {/* Context Action Buttons */}
                    <div className="flex flex-wrap gap-1.5">
                      {(t.status === 'DISCOVERED' || t.status === 'GATE1_PENDING') && (
                        <>
                          <Button
                            size="sm"
                            variant="primary"
                            onClick={() => handleGateDecision(t.target_id, true, undefined, true)}
                          >
                            通过并克隆
                          </Button>
                          <Button
                            size="sm"
                            variant="secondary"
                            onClick={() => runStageQuick('triage_project', t.target_id)}
                          >
                            价值预判
                          </Button>
                        </>
                      )}
                      {t.status === 'CLONED' && (
                        <Button
                          size="sm"
                          variant="primary"
                          onClick={() => runStageQuick('surface_map', t.target_id)}
                        >
                          <Play className="h-3 w-3" /> 安全面测绘
                        </Button>
                      )}
                      {t.status === 'MAPPED' && (
                        <Button
                          size="sm"
                          variant="primary"
                          onClick={() => runStageQuick('deep_audit', t.target_id)}
                        >
                          <Play className="h-3 w-3" /> 深度审计
                        </Button>
                      )}
                      {t.status === 'AUDITED' && (
                        <Button
                          size="sm"
                          variant="primary"
                          onClick={() => runStageQuick('triage_vuln', t.target_id)}
                        >
                          <Play className="h-3 w-3" /> 漏洞复核
                        </Button>
                      )}
                    </div>

                    {/* Candidates under target */}
                    {(t.candidates || []).length > 0 && (
                      <div className="space-y-1 border-t border-[var(--border)] pt-2">
                        {t.candidates.map((c: any) => (
                          <button
                            key={c.candidate_id}
                            type="button"
                            onClick={() => openCandidateEvidence(t.target_id, c.candidate_id)}
                            className="flex w-full items-center justify-between rounded-lg px-2 py-1.5 text-left text-xs hover:bg-[var(--surface-hover)] cursor-pointer"
                          >
                            <span className="font-mono font-medium">{c.candidate_id}</span>
                            <StatusPill tone={STATUS_TONE[c.status] || 'neutral'}>
                              {c.status}
                            </StatusPill>
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                ))
              )}
            </div>
          ) : (
            <div className="flex-1 overflow-y-auto p-3 space-y-3">
              {!selectedCand || !candDetail ? (
                <div className="tahoe-card p-6 text-center text-xs text-[var(--muted)]">
                  <ImageIcon className="mx-auto mb-2 h-6 w-6 text-[var(--subtle)]" />
                  在「目标」列表中点击任意漏洞候选（如 CAND-01），即可预览证据图与一键复制 CNVD 栏位。
                </div>
              ) : (
                <>
                  <div className="tahoe-card p-3 space-y-2">
                    <div className="flex items-center justify-between">
                      <span className="font-mono text-xs font-semibold">
                        {selectedCand.candidate}
                      </span>
                      <div className="flex gap-1.5">
                        <Button
                          size="sm"
                          variant="primary"
                          onClick={() => generateReport(selectedCand.target, selectedCand.candidate)}
                        >
                          <FileText className="h-3 w-3" /> 生成报告
                        </Button>
                        {candDetail.report_path && (
                          <a
                            href={`/api/download-docx/${encodeURIComponent(selectedCand.target)}/${encodeURIComponent(selectedCand.candidate)}`}
                            className="inline-flex h-7 items-center gap-1 rounded-lg border border-[var(--border)] bg-[var(--surface)] px-2 text-xs hover:bg-[var(--surface-hover)]"
                          >
                            <Download className="h-3 w-3" /> .docx
                          </a>
                        )}
                      </div>
                    </div>
                  </div>

                  {/* Evidence Images */}
                  {(candDetail.evidence_images || []).length > 0 && (
                    <div className="tahoe-card p-3 space-y-2">
                      <div className="text-xs font-semibold">自动取证截图</div>
                      <div className="grid grid-cols-2 gap-2">
                        {candDetail.evidence_images.map((img: any) => {
                          const url = `/api/evidence/${encodeURIComponent(selectedCand.target)}/${encodeURIComponent(selectedCand.candidate)}/${encodeURIComponent(img.name)}`
                          return (
                            <button
                              key={img.name}
                              type="button"
                              onClick={() => setLightboxImg(url)}
                              className="overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--surface-subtle)] text-left hover:border-[var(--border-strong)] cursor-pointer"
                            >
                              <img src={url} alt={img.name} className="h-20 w-full object-cover" />
                              <div className="truncate px-1.5 py-1 font-mono text-[10px] text-[var(--muted)]">
                                {img.name}
                              </div>
                            </button>
                          )
                        })}
                      </div>
                    </div>
                  )}

                  {/* CNVD Form 1-Click Copy */}
                  {candDetail.cnvd_form && (
                    <div className="tahoe-card divide-y divide-[var(--border)] overflow-hidden">
                      <div className="bg-[var(--surface-subtle)] px-3 py-2 text-xs font-semibold">
                        CNVD 提报栏位（点击复制）
                      </div>
                      {Object.entries(candDetail.cnvd_form)
                        .filter(([, v]) => v !== null && v !== undefined && String(v).trim() !== '')
                        .map(([k, v]) => (
                          <div key={k} className="px-3 py-2 space-y-1">
                            <div className="flex items-center justify-between">
                              <span className="font-mono text-[11px] text-[var(--muted)]">{k}</span>
                              <button
                                type="button"
                                onClick={() =>
                                  copyText(k, typeof v === 'string' ? v : JSON.stringify(v, null, 2))
                                }
                                className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10.5px] text-[var(--muted)] hover:bg-[var(--control-bg)] hover:text-[var(--fg)] cursor-pointer"
                              >
                                <Copy className="h-3 w-3" /> 复制
                              </button>
                            </div>
                            <div className="line-clamp-3 text-xs text-[var(--fg-secondary)]">
                              {typeof v === 'string' ? v : JSON.stringify(v)}
                            </div>
                          </div>
                        ))}
                    </div>
                  )}
                </>
              )}
            </div>
          )}
        </aside>
      )}

      {/* Lightbox for Evidence Image */}
      {lightboxImg && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-8"
          onClick={() => setLightboxImg(null)}
        >
          <div className="relative max-h-full max-w-5xl" onClick={(e) => e.stopPropagation()}>
            <div className="mb-2 flex justify-end gap-2">
              <a
                href={lightboxImg}
                target="_blank"
                rel="noreferrer"
                className="inline-flex h-8 items-center gap-1 rounded-lg bg-white/15 px-3 text-xs text-white hover:bg-white/25"
              >
                <ExternalLink className="h-3.5 w-3.5" /> 新标签打开
              </a>
              <button
                type="button"
                onClick={() => setLightboxImg(null)}
                className="flex h-8 w-8 items-center justify-center rounded-lg bg-white/15 text-white hover:bg-white/25 cursor-pointer"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <img
              src={lightboxImg}
              alt="Evidence preview"
              className="max-h-[82vh] rounded-xl border border-white/15 object-contain shadow-2xl"
            />
          </div>
        </div>
      )}
    </div>
  )
}
