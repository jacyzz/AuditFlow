import { useEffect, useMemo, useRef, useState } from 'react'
import { marked } from 'marked'
import CodeMirror from '@uiw/react-codemirror'
import { markdown } from '@codemirror/lang-markdown'
import { yaml } from '@codemirror/lang-yaml'
import { oneDark } from '@codemirror/theme-one-dark'
import { Panel, Group as PanelGroup, Separator as PanelResizeHandle } from 'react-resizable-panels'
import {
  Code2,
  Columns2,
  Eye,
  GitFork,
  Plus,
  RotateCcw,
  Save,
  Search,
  Trash2,
  Upload,
} from 'lucide-react'
import { api } from '../api'
import {
  Button,
  Field,
  Input,
  Modal,
  SegmentedControl,
  Select,
  StatusPill,
  cn,
} from '../components/ui'

interface Props {
  toast: (msg: string) => void
  onRefresh: () => Promise<void>
  dark: boolean
}

const STAGE_LABELS: Record<string, string> = {
  dispatcher: '总控调度',
  scout: '项目发现',
  triage_project: '项目预判',
  surface_map: '安全面测绘',
  deep_audit: '深度审计',
  triage_vuln: '漏洞复核',
  verify: '隔离验证',
  report: '报告写作',
}

function stripFrontmatter(md: string): string {
  return md.replace(/^---\r?\n[\s\S]*?\r?\n---\r?\n?/, '')
}

export default function SkillStudio({ toast, onRefresh, dark }: Props) {
  const [skills, setSkills] = useState<any[]>([])
  const [search, setSearch] = useState('')
  const [selectedName, setSelectedName] = useState('')
  const [detail, setDetail] = useState<any>(null)
  const [promptMd, setPromptMd] = useState('')
  const [manifestYaml, setManifestYaml] = useState('')
  const [viewMode, setViewMode] = useState<'preview' | 'split' | 'yaml'>('split')
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)

  // Modals
  const [showCreate, setShowCreate] = useState(false)
  const [createForm, setCreateForm] = useState({
    name: '',
    stage: 'deep_audit',
    description: '',
    prompt_markdown: '# 自定义审计 Skill\n\n## 目标\n描述本 Skill 聚焦的漏洞类别与代码入口。\n\n## 排查清单\n1. 检查未鉴权路由\n2. 追踪可控参数流向危险 Sink\n',
  })

  const [showFork, setShowFork] = useState(false)
  const [forkName, setForkName] = useState('')
  const fileInputRef = useRef<HTMLInputElement | null>(null)

  const loadList = async (focusName?: string) => {
    try {
      const res = await api<any>('/api/skills')
      const list = res.skills || []
      setSkills(list)
      const target =
        focusName ||
        (selectedName && list.some((s: any) => s.name === selectedName)
          ? selectedName
          : list[0]?.name || '')
      if (target) setSelectedName(target)
    } catch (e: any) {
      toast('加载 Skill 列表失败: ' + e.message)
    }
  }

  const loadDetail = async (name: string) => {
    if (!name) return
    try {
      const res = await api<any>(`/api/skills/detail?name=${encodeURIComponent(name)}`)
      setDetail(res.skill)
      setPromptMd(res.skill.prompt_markdown || '')
      setManifestYaml(res.skill.manifest_yaml || '')
      setDirty(false)
    } catch (e: any) {
      toast('读取 Skill 详情失败: ' + e.message)
    }
  }

  useEffect(() => {
    loadList()
  }, [])

  useEffect(() => {
    if (selectedName) loadDetail(selectedName)
  }, [selectedName])

  const grouped = useMemo(() => {
    const q = search.trim().toLowerCase()
    const filtered = skills.filter(
      (s) =>
        !q ||
        s.name.toLowerCase().includes(q) ||
        (s.description || '').toLowerCase().includes(q) ||
        (s.stage || '').toLowerCase().includes(q),
    )
    const map: Record<string, any[]> = {}
    for (const s of filtered) {
      const k = s.stage || 'other'
      if (!map[k]) map[k] = []
      map[k].push(s)
    }
    return map
  }, [skills, search])

  const saveSkill = async () => {
    if (!detail) return
    setSaving(true)
    try {
      const res = await api<any>('/api/skills/save', 'POST', {
        name: detail.name,
        manifest_yaml: manifestYaml,
        prompt_markdown: promptMd,
      })
      setDetail(res.skill)
      setDirty(false)
      toast(`已保存到覆盖层 skills_custom/：${detail.name}`)
      await loadList(detail.name)
      await onRefresh()
    } catch (e: any) {
      toast('保存失败: ' + e.message)
    } finally {
      setSaving(false)
    }
  }

  const createSkill = async () => {
    if (!createForm.name.trim()) {
      toast('请输入 Skill 名称（例如 audit/mcp-sandbox-escape）')
      return
    }
    try {
      const res = await api<any>('/api/skills/create', 'POST', createForm)
      toast(`已创建自定义 Skill：${res.skill.name}`)
      setShowCreate(false)
      await loadList(res.skill.name)
      await loadDetail(res.skill.name)
      await onRefresh()
    } catch (e: any) {
      toast('创建失败: ' + e.message)
    }
  }

  const forkSkill = async () => {
    if (!detail || !forkName.trim()) return
    try {
      const res = await api<any>('/api/skills/fork', 'POST', {
        source_name: detail.name,
        new_name: forkName.trim(),
      })
      toast(`已派生新 Skill：${res.skill.name}`)
      setShowFork(false)
      setForkName('')
      await loadList(res.skill.name)
      await loadDetail(res.skill.name)
      await onRefresh()
    } catch (e: any) {
      toast('Fork 失败: ' + e.message)
    }
  }

  const resetOrDelete = async () => {
    if (!detail) return
    try {
      const res = await api<any>('/api/skills/reset', 'POST', { name: detail.name })
      toast(res.action === 'deleted' ? `已删除自定义 Skill：${detail.name}` : `已恢复为内置默认版本：${detail.name}`)
      await loadList()
      await onRefresh()
    } catch (e: any) {
      toast('操作失败: ' + e.message)
    }
  }

  const handleImportMd = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    const reader = new FileReader()
    reader.onload = () => {
      const slug = file.name.replace(/\.md$/i, '').toLowerCase().replace(/[^a-z0-9_-]+/g, '-')
      setCreateForm((prev) => ({
        ...prev,
        name: `audit/${slug || 'imported-skill'}`,
        description: `从 ${file.name} 导入的自定义 Skill`,
        prompt_markdown: String(reader.result || ''),
      }))
      setShowCreate(true)
    }
    reader.readAsText(file)
    e.target.value = ''
  }

  const sourceBadge = (source: string) => {
    if (source === 'override') return <StatusPill tone="warn">已覆写</StatusPill>
    if (source === 'custom') return <StatusPill tone="ok">自定义</StatusPill>
    return <StatusPill tone="neutral">内置</StatusPill>
  }

  return (
    <div className="flex h-full overflow-hidden">
      {/* Left Categorized Skill Tree */}
      <aside className="flex w-[264px] shrink-0 flex-col border-r border-[var(--border)] bg-[var(--surface-subtle)]">
        <div className="space-y-2.5 border-b border-[var(--border)] p-3">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-[var(--fg)]">
              Skill 工坊 ({skills.length})
            </span>
            <div className="flex items-center gap-1">
              <button
                type="button"
                title="导入本地 .md 文件"
                onClick={() => fileInputRef.current?.click()}
                className="flex h-7 w-7 items-center justify-center rounded-lg border border-[var(--border)] bg-[var(--surface)] text-[var(--muted)] hover:text-[var(--fg)] cursor-pointer"
              >
                <Upload className="h-3.5 w-3.5" />
              </button>
              <Button size="sm" variant="primary" onClick={() => setShowCreate(true)}>
                <Plus className="h-3.5 w-3.5" /> 新建
              </Button>
              <input
                ref={fileInputRef}
                type="file"
                accept=".md,.markdown,.txt"
                className="hidden"
                onChange={handleImportMd}
              />
            </div>
          </div>

          <div className="relative">
            <Search className="pointer-events-none absolute left-2.5 top-2 h-3.5 w-3.5 text-[var(--subtle)]" />
            <Input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="搜索 Skill 名称或描述..."
              className="pl-8"
            />
          </div>
        </div>

        <div className="flex-1 space-y-4 overflow-y-auto p-2.5">
          {Object.entries(grouped).map(([stage, list]) => (
            <div key={stage}>
              <div className="mb-1 px-2 text-[10.5px] font-semibold tracking-wide text-[var(--subtle)] uppercase">
                {STAGE_LABELS[stage] || stage}
              </div>
              <div className="space-y-0.5">
                {list.map((s) => {
                  const active = s.name === selectedName
                  return (
                    <button
                      key={s.name}
                      type="button"
                      onClick={() => setSelectedName(s.name)}
                      className={cn(
                        'flex w-full items-center justify-between gap-2 rounded-[8px] px-2.5 py-2 text-left transition-colors cursor-pointer',
                        active
                          ? 'bg-[var(--surface-active)] font-medium text-[var(--fg)]'
                          : 'text-[var(--fg-secondary)] hover:bg-[var(--surface-hover)]',
                      )}
                    >
                      <div className="min-w-0">
                        <div className="truncate font-mono text-[12px]">{s.name}</div>
                        <div className="truncate text-[11px] text-[var(--muted)]">
                          {s.description}
                        </div>
                      </div>
                      {s.source !== 'builtin' && (
                        <span
                          className={cn(
                            'h-1.5 w-1.5 shrink-0 rounded-full',
                            s.source === 'custom' ? 'bg-[var(--ok)]' : 'bg-[var(--warn)]',
                          )}
                        />
                      )}
                    </button>
                  )
                })}
              </div>
            </div>
          ))}
        </div>
      </aside>

      {/* Main Editor & Preview Area */}
      <div className="flex flex-1 flex-col overflow-hidden bg-[var(--surface)]">
        {detail ? (
          <>
            {/* Top Editor Toolbar */}
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--border)] px-5 py-3">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <h1 className="truncate font-mono text-[14.5px] font-semibold">{detail.name}</h1>
                  {sourceBadge(detail.source)}
                  {dirty && <StatusPill tone="info">未保存</StatusPill>}
                </div>
                <p className="mt-0.5 truncate text-xs text-[var(--muted)]">{detail.description}</p>
              </div>

              <div className="flex items-center gap-2">
                <SegmentedControl
                  value={viewMode}
                  onChange={setViewMode}
                  options={[
                    { value: 'preview', label: '预览', icon: <Eye className="h-3.5 w-3.5" /> },
                    { value: 'split', label: '双栏编辑', icon: <Columns2 className="h-3.5 w-3.5" /> },
                    { value: 'yaml', label: 'skill.yaml', icon: <Code2 className="h-3.5 w-3.5" /> },
                  ]}
                />
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => {
                    setForkName(`${detail.name}-custom`)
                    setShowFork(true)
                  }}
                >
                  <GitFork className="h-3.5 w-3.5" /> Fork
                </Button>
                {(detail.can_reset || detail.can_delete) && (
                  <Button size="sm" variant="danger" onClick={resetOrDelete}>
                    {detail.can_delete ? (
                      <>
                        <Trash2 className="h-3.5 w-3.5" /> 删除
                      </>
                    ) : (
                      <>
                        <RotateCcw className="h-3.5 w-3.5" /> 恢复内置
                      </>
                    )}
                  </Button>
                )}
                <Button size="sm" variant="primary" disabled={saving || !dirty} onClick={saveSkill}>
                  <Save className="h-3.5 w-3.5" /> {saving ? '保存中...' : '保存'}
                </Button>
              </div>
            </div>

            {/* Editor Surface */}
            <div className="flex-1 overflow-hidden">
              {viewMode === 'preview' && (
                <div className="h-full overflow-y-auto px-10 py-7">
                  <div
                    className="md-prose mx-auto max-w-3xl"
                    dangerouslySetInnerHTML={{
                      __html: marked.parse(stripFrontmatter(promptMd || '')) as string,
                    }}
                  />
                </div>
              )}

              {viewMode === 'split' && (
                <PanelGroup orientation="horizontal" className="h-full">
                  <Panel defaultSize={52} minSize={28}>
                    <div className="flex h-full flex-col">
                      <div className="border-b border-[var(--border)] bg-[var(--surface-subtle)] px-4 py-1.5 font-mono text-[11px] text-[var(--muted)]">
                        SKILL.md（修改自动落盘至 skills_custom/，不破坏内置原文件）
                      </div>
                      <div className="flex-1 overflow-hidden">
                        <CodeMirror
                          value={promptMd}
                          height="100%"
                          theme={dark ? oneDark : 'light'}
                          extensions={[markdown()]}
                          onChange={(val) => {
                            setPromptMd(val)
                            setDirty(true)
                          }}
                          basicSetup={{ lineNumbers: true, foldGutter: true, highlightActiveLine: true }}
                        />
                      </div>
                    </div>
                  </Panel>
                  <PanelResizeHandle className="w-1 bg-[var(--border)] transition-colors hover:bg-[var(--primary)]/40 cursor-col-resize" />
                  <Panel defaultSize={48} minSize={25}>
                    <div className="flex h-full flex-col">
                      <div className="border-b border-[var(--border)] bg-[var(--surface-subtle)] px-4 py-1.5 text-[11px] text-[var(--muted)]">
                        实时 Markdown 渲染预览
                      </div>
                      <div className="flex-1 overflow-y-auto px-7 py-5">
                        <div
                          className="md-prose"
                          dangerouslySetInnerHTML={{
                      __html: marked.parse(stripFrontmatter(promptMd || '')) as string,
                    }}
                        />
                      </div>
                    </div>
                  </Panel>
                </PanelGroup>
              )}

              {viewMode === 'yaml' && (
                <div className="flex h-full flex-col">
                  <div className="border-b border-[var(--border)] bg-[var(--surface-subtle)] px-4 py-1.5 font-mono text-[11px] text-[var(--muted)]">
                    skill.yaml（定义输入输出契约、适用阶段与推荐适配器）
                  </div>
                  <div className="flex-1 overflow-hidden">
                    <CodeMirror
                      value={manifestYaml}
                      height="100%"
                      theme={dark ? oneDark : 'light'}
                      extensions={[yaml()]}
                      onChange={(val) => {
                        setManifestYaml(val)
                        setDirty(true)
                      }}
                      basicSetup={{ lineNumbers: true, foldGutter: true }}
                    />
                  </div>
                </div>
              )}
            </div>
          </>
        ) : (
          <div className="flex h-full items-center justify-center text-sm text-[var(--muted)]">
            请从左侧选择一个 Skill 查看或编辑
          </div>
        )}
      </div>

      {/* Create Skill Modal */}
      <Modal
        open={showCreate}
        onClose={() => setShowCreate(false)}
        title="新建自定义 Skill"
        description="将保存在 skills_custom/ 目录，立即可在「编排画布」中选择绑定。"
        footer={
          <>
            <Button variant="secondary" onClick={() => setShowCreate(false)}>
              取消
            </Button>
            <Button variant="primary" onClick={createSkill}>
              创建 Skill
            </Button>
          </>
        }
      >
        <div className="space-y-3.5">
          <div className="grid grid-cols-2 gap-3">
            <Field label="Skill 名称" hint="格式 category/slug">
              <Input
                className="font-mono"
                value={createForm.name}
                onChange={(e) => setCreateForm({ ...createForm, name: e.target.value })}
                placeholder="audit/ai-mcp-rce"
              />
            </Field>
            <Field label="所属阶段">
              <Select
                value={createForm.stage}
                onChange={(e) => setCreateForm({ ...createForm, stage: e.target.value })}
              >
                {Object.entries(STAGE_LABELS).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v} ({k})
                  </option>
                ))}
              </Select>
            </Field>
          </div>
          <Field label="简介">
            <Input
              value={createForm.description}
              onChange={(e) => setCreateForm({ ...createForm, description: e.target.value })}
              placeholder="针对 MCP Server 工具调用与沙箱逃逸的定向源码审计"
            />
          </Field>
          <Field label="SKILL.md 初始内容">
            <textarea
              rows={8}
              value={createForm.prompt_markdown}
              onChange={(e) => setCreateForm({ ...createForm, prompt_markdown: e.target.value })}
              className="w-full rounded-[10px] border border-[var(--border)] bg-[var(--surface-subtle)] p-3 font-mono text-xs text-[var(--fg)]"
            />
          </Field>
        </div>
      </Modal>

      {/* Fork Skill Modal */}
      <Modal
        open={showFork}
        onClose={() => setShowFork(false)}
        title={`Fork Skill · ${detail?.name}`}
        description="基于当前 Skill 派生一个独立副本到 skills_custom/。"
        footer={
          <>
            <Button variant="secondary" onClick={() => setShowFork(false)}>
              取消
            </Button>
            <Button variant="primary" onClick={forkSkill}>
              确认派生
            </Button>
          </>
        }
      >
        <Field label="新 Skill 名称" hint="格式 category/slug">
          <Input
            className="font-mono"
            value={forkName}
            onChange={(e) => setForkName(e.target.value)}
            placeholder="audit/my-custom-fork"
          />
        </Field>
      </Modal>
    </div>
  )
}
