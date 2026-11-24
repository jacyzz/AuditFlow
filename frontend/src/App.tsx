import { useEffect, useState } from 'react'
import {
  Bot,
  BookOpen,
  GitBranch,
  MessageSquare,
  Moon,
  Settings,
  ShieldCheck,
  Sun,
} from 'lucide-react'
import { api } from './api'
import ChatWorkspace from './pages/ChatWorkspace'
import WorkflowStudio from './pages/WorkflowStudio'
import SkillStudio from './pages/SkillStudio'
import AgentHub from './pages/AgentHub'
import SettingsPage from './pages/SettingsPage'

type Page = 'chat' | 'workflow' | 'skills' | 'agents' | 'settings'

export default function App() {
  const [page, setPage] = useState<Page>('chat')
  const [dark, setDark] = useState(true)
  const [toastMsg, setToastMsg] = useState<string | null>(null)
  const [overview, setOverview] = useState<any>(null)

  const toast = (msg: string) => {
    setToastMsg(msg)
    window.clearTimeout((window as any).__afToast)
    ;(window as any).__afToast = window.setTimeout(() => setToastMsg(null), 4000)
  }

  const refreshOverview = async () => {
    try {
      const data = await api('/api/overview')
      setOverview(data)
    } catch (e: any) {
      toast('刷新工作区失败: ' + e.message)
    }
  }

  useEffect(() => {
    document.documentElement.classList.toggle('dark', dark)
  }, [dark])

  useEffect(() => {
    refreshOverview()
  }, [])

  const enabledAgentCount = (overview?.agent_profiles || []).filter((a: any) => a.enabled).length
  const gateBadge = (overview?.counts?.gate1_pending || 0) + (overview?.counts?.gate2_pending || 0)

  const navItems: { id: Page; label: string; icon: any; badge?: number }[] = [
    { id: 'chat', label: '对话工作台', icon: MessageSquare, badge: gateBadge || undefined },
    { id: 'workflow', label: '编排画布', icon: GitBranch },
    { id: 'skills', label: 'Skill 管理', icon: BookOpen },
    { id: 'agents', label: 'Agent 能力中心', icon: Bot },
    { id: 'settings', label: '环境设置', icon: Settings },
  ]

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-[var(--bg)] text-[var(--fg)]">
      {/* Left Navigation Sidebar */}
      <aside className="flex w-56 shrink-0 flex-col border-r border-[var(--border)] bg-[var(--surface)]">
        <div className="flex items-center gap-2.5 border-b border-[var(--border)] px-4 py-4">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-sky-500/15 text-sky-400">
            <ShieldCheck className="h-5 w-5" />
          </div>
          <div>
            <div className="text-sm font-bold tracking-tight">AuditFlow Studio</div>
            <div className="text-[11px] text-[var(--muted)]">v2.0 · Multi-Agent</div>
          </div>
        </div>

        <nav className="flex-1 space-y-1 p-2.5">
          {navItems.map((item) => {
            const Icon = item.icon
            const active = page === item.id
            return (
              <button
                key={item.id}
                onClick={() => setPage(item.id)}
                className={`flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-sm transition ${
                  active
                    ? 'bg-sky-500/15 font-medium text-sky-400'
                    : 'text-[var(--muted)] hover:bg-[var(--surface-2)] hover:text-[var(--fg)]'
                }`}
              >
                <span className="flex items-center gap-2.5">
                  <Icon className="h-4 w-4" />
                  {item.label}
                </span>
                {item.badge ? (
                  <span className="rounded-full bg-amber-500/20 px-1.5 py-0.5 text-[11px] font-semibold text-amber-400">
                    {item.badge}
                  </span>
                ) : null}
              </button>
            )
          })}
        </nav>

        <div className="border-t border-[var(--border)] p-3 text-xs">
          <div className="mb-2 flex items-center justify-between rounded-lg bg-[var(--surface-2)] px-2.5 py-2">
            <span className="text-[var(--muted)]">已启用 Agent</span>
            <span className="font-semibold text-emerald-400">{enabledAgentCount} 个</span>
          </div>
          <button
            onClick={() => setDark((d) => !d)}
            className="flex w-full items-center justify-center gap-2 rounded-lg border border-[var(--border)] py-1.5 text-[var(--muted)] hover:bg-[var(--surface-2)] hover:text-[var(--fg)]"
          >
            {dark ? <Sun className="h-3.5 w-3.5" /> : <Moon className="h-3.5 w-3.5" />}
            {dark ? '切换浅色主题' : '切换暗色主题'}
          </button>
        </div>
      </aside>

      {/* Main Content */}
      <main className="flex-1 overflow-hidden">
        {page === 'chat' && (
          <ChatWorkspace overview={overview} onRefresh={refreshOverview} toast={toast} />
        )}
        {page === 'workflow' && (
          <WorkflowStudio overview={overview} onRefresh={refreshOverview} toast={toast} />
        )}
        {page === 'skills' && <SkillStudio toast={toast} onRefresh={refreshOverview} />}
        {page === 'agents' && <AgentHub toast={toast} onRefresh={refreshOverview} />}
        {page === 'settings' && <SettingsPage toast={toast} />}
      </main>

      {toastMsg && (
        <div className="fixed right-5 bottom-5 z-50 max-w-md rounded-xl border border-sky-500/40 bg-[var(--surface)] px-4 py-3 text-sm shadow-2xl">
          {toastMsg}
        </div>
      )}
    </div>
  )
}
