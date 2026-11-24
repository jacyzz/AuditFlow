import { useEffect, useState } from 'react'
import {
  Bot,
  BookOpen,
  GitBranch,
  MessageSquare,
  Moon,
  RefreshCw,
  Settings,
  ShieldCheck,
  Sun,
} from 'lucide-react'
import { Toaster, toast as sonnerToast } from 'sonner'
import { api } from './api'
import { AgentIcon } from './components/AgentIcon'
import { cn } from './components/ui'
import ChatWorkspace from './pages/ChatWorkspace'
import WorkflowStudio from './pages/WorkflowStudio'
import SkillStudio from './pages/SkillStudio'
import AgentHub from './pages/AgentHub'
import SettingsPage from './pages/SettingsPage'

type Page = 'chat' | 'workflow' | 'skills' | 'agents' | 'settings'

export default function App() {
  const [page, setPage] = useState<Page>('chat')
  const [dark, setDark] = useState<boolean>(() => {
    try {
      return localStorage.getItem('auditflow-theme') === 'dark'
    } catch {
      return false
    }
  })
  const [overview, setOverview] = useState<any>(null)
  const [refreshing, setRefreshing] = useState(false)

  const toast = (msg: string) => {
    if (msg.includes('失败') || msg.includes('错误')) {
      sonnerToast.error(msg)
    } else {
      sonnerToast(msg)
    }
  }

  const refreshOverview = async () => {
    setRefreshing(true)
    try {
      const data = await api('/api/overview')
      setOverview(data)
    } catch (e: any) {
      sonnerToast.error('刷新工作区失败: ' + e.message)
    } finally {
      setRefreshing(false)
    }
  }

  useEffect(() => {
    document.documentElement.classList.toggle('dark', dark)
    try {
      localStorage.setItem('auditflow-theme', dark ? 'dark' : 'light')
    } catch {
      /* ignore */
    }
  }, [dark])

  useEffect(() => {
    refreshOverview()
  }, [])

  const enabledAgents = (overview?.agent_profiles || []).filter((a: any) => a.enabled)
  const gateBadge = (overview?.counts?.gate1_pending || 0) + (overview?.counts?.gate2_pending || 0)

  const navItems: { id: Page; label: string; icon: any; badge?: number }[] = [
    { id: 'chat', label: '对话工作台', icon: MessageSquare, badge: gateBadge || undefined },
    { id: 'workflow', label: '编排画布', icon: GitBranch },
    { id: 'skills', label: 'Skill 工坊', icon: BookOpen },
    { id: 'agents', label: 'Agent 中心', icon: Bot },
    { id: 'settings', label: '环境设置', icon: Settings },
  ]

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-[var(--shell)] text-[var(--fg)]">
      {/* Tahoe Navigation Layer (Frame) */}
      <aside className="flex w-[224px] shrink-0 flex-col justify-between px-2.5 py-3 select-none">
        <div>
          {/* Brand Header */}
          <div className="flex items-center justify-between px-2 pb-4 pt-0.5">
            <div className="flex items-center gap-2.5">
              <div className="flex h-7 w-7 items-center justify-center rounded-[8px] bg-[var(--primary)] text-[var(--primary-fg)] shadow-[var(--shadow-xs)]">
                <ShieldCheck className="h-4 w-4" />
              </div>
              <div className="leading-tight">
                <div className="text-[13.5px] font-semibold tracking-[-0.015em]">AuditFlow</div>
                <div className="text-[11px] text-[var(--muted)]">Security Studio</div>
              </div>
            </div>
            <button
              type="button"
              title="刷新工作区"
              onClick={refreshOverview}
              className="flex h-7 w-7 items-center justify-center rounded-lg text-[var(--muted)] hover:bg-[var(--control-bg)] hover:text-[var(--fg)] cursor-pointer"
            >
              <RefreshCw className={cn('h-3.5 w-3.5', refreshing && 'animate-spin')} />
            </button>
          </div>

          {/* Primary Navigation */}
          <div className="px-2 pb-1.5 text-[10.5px] font-medium tracking-wide text-[var(--subtle)] uppercase">
            工作区
          </div>
          <nav className="space-y-0.5">
            {navItems.map((item) => {
              const Icon = item.icon
              const active = page === item.id
              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => setPage(item.id)}
                  className={cn(
                    'flex h-9 w-full items-center justify-between rounded-[10px] px-2.5 text-[13px] font-medium transition-colors duration-150 cursor-pointer',
                    active
                      ? 'bg-[var(--primary)] text-[var(--primary-fg)] shadow-[var(--shadow-xs)]'
                      : 'text-[var(--fg-secondary)] hover:bg-[var(--control-bg)] hover:text-[var(--fg)]',
                  )}
                >
                  <span className="flex items-center gap-2.5">
                    <Icon className="h-4 w-4 shrink-0 opacity-90" />
                    {item.label}
                  </span>
                  {item.badge ? (
                    <span
                      className={cn(
                        'rounded-full px-1.5 py-0.5 text-[10.5px] font-semibold leading-none',
                        active
                          ? 'bg-[var(--primary-fg)]/20 text-[var(--primary-fg)]'
                          : 'bg-[var(--warn-bg)] text-[var(--warn)]',
                      )}
                    >
                      {item.badge}
                    </span>
                  ) : null}
                </button>
              )
            })}
          </nav>
        </div>

        {/* Bottom Agent Roster & Appearance */}
        <div className="space-y-2 pt-3">
          <button
            type="button"
            onClick={() => setPage('agents')}
            className="w-full rounded-[10px] border border-[var(--border)] bg-[var(--surface)] px-2.5 py-2 text-left transition-colors hover:bg-[var(--surface-hover)] cursor-pointer"
          >
            <div className="flex items-center justify-between">
              <span className="text-[11px] font-medium text-[var(--muted)]">出战 Agent</span>
              <span className="text-[11px] font-semibold text-[var(--fg)]">
                {enabledAgents.length} 已启用
              </span>
            </div>
            <div className="mt-1.5 flex items-center gap-1.5 overflow-hidden">
              {enabledAgents.slice(0, 6).map((a: any) => (
                <span
                  key={a.name}
                  title={a.display_name}
                  className="flex h-6 w-6 items-center justify-center rounded-md border border-[var(--border)] bg-[var(--surface-subtle)]"
                >
                  <AgentIcon agent={a.name} dark={dark} size={14} />
                </span>
              ))}
              {enabledAgents.length === 0 && (
                <span className="text-[11px] text-[var(--subtle)]">点击配置本机 Agent</span>
              )}
            </div>
          </button>

          <button
            type="button"
            onClick={() => setDark((d) => !d)}
            className="flex h-8 w-full items-center justify-between rounded-[10px] px-2.5 text-xs font-medium text-[var(--muted)] transition-colors hover:bg-[var(--control-bg)] hover:text-[var(--fg)] cursor-pointer"
          >
            <span className="flex items-center gap-2">
              {dark ? <Sun className="h-3.5 w-3.5" /> : <Moon className="h-3.5 w-3.5" />}
              {dark ? '切换浅色外观' : '切换深色外观'}
            </span>
            <span className="text-[10.5px] text-[var(--subtle)]">{dark ? 'Dark' : 'Light'}</span>
          </button>
        </div>
      </aside>

      {/* Tahoe Content Layer — Crisp Inset Opaque Window */}
      <main className="flex-1 overflow-hidden p-2 pl-0">
        <div className="h-full w-full overflow-hidden rounded-[12px] border border-[var(--border)] bg-[var(--surface)]">
          {page === 'chat' && (
            <ChatWorkspace overview={overview} onRefresh={refreshOverview} toast={toast} dark={dark} />
          )}
          {page === 'workflow' && (
            <WorkflowStudio overview={overview} onRefresh={refreshOverview} toast={toast} dark={dark} />
          )}
          {page === 'skills' && (
            <SkillStudio toast={toast} onRefresh={refreshOverview} dark={dark} />
          )}
          {page === 'agents' && (
            <AgentHub toast={toast} onRefresh={refreshOverview} dark={dark} />
          )}
          {page === 'settings' && <SettingsPage toast={toast} dark={dark} />}
        </div>
      </main>

      <Toaster
        position="bottom-right"
        theme={dark ? 'dark' : 'light'}
        toastOptions={{
          style: {
            background: 'var(--surface)',
            color: 'var(--fg)',
            border: '1px solid var(--border)',
            borderRadius: '10px',
            fontSize: '13px',
          },
        }}
      />
    </div>
  )
}
