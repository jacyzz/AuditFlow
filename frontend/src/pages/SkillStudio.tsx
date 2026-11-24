import { useEffect, useState } from 'react'
import {
  CopyPlus,
  Eye,
  FileCode2,
  Plus,
  RotateCcw,
  Save,
  Search,
  SplitSquareHorizontal,
  Trash2,
  Upload,
} from 'lucide-react'
import { api, renderMarkdown } from '../api'

interface Props {
  toast: (msg: string) => void
  onRefresh: () => Promise<void>
}

export default function SkillStudio({ toast, onRefresh }: Props) {
  const [skills, setSkills] = useState<any[]>([])
  const [query, setQuery] = useState('')
  const [selectedName, setSelectedName] = useState<string>('')
  const [detail, setDetail] = useState<any>(null)
  const [manifestYaml, setManifestYaml] = useState('')
  const [promptMd, setPromptMd] = useState('')
  const [viewMode, setViewMode] = useState<'split' | 'preview' | 'edit'>('split')
  const [showCreate, setShowCreate] = useState(false)
  const [newSkill, setNewSkill] = useState({
    name: 'audit/my-custom-rule',
    stage: 'deep_audit',
    description: '自定义专项安全审计规则',
    prompt_markdown: '# 自定义审计 Skill\n\n## 排查目标\n- \n\n## 输出要求\n严格遵循 `docs/SCHEMAS.md`。',
  })

  const loadSkills = async () => {
    try {
      const res = await api<{ skills: any[] }>('/api/skills')
      setSkills(res.skills)
      if (!selectedName && res.skills.length) {
        selectSkill(res.skills[0].name)
      }
    } catch (e: any) {
      toast('加载 Skill 列表失败: ' + e.message)
    }
  }

  const selectSkill = async (name: string) => {
    setSelectedName(name)
    try {
      const res = await api<{ skill: any }>(`/api/skills/detail?name=${encodeURIComponent(name)}`)
      setDetail(res.skill)
      setManifestYaml(res.skill.manifest_yaml)
      setPromptMd(res.skill.prompt_markdown)
    } catch (e: any) {
      toast('读取 Skill 失败: ' + e.message)
    }
  }

  useEffect(() => {
    loadSkills()
  }, [])

  const saveSkill = async () => {
    if (!detail) return
    try {
      const res = await api<{ skill: any }>('/api/skills/save', 'POST', {
        name: detail.name,
        manifest_yaml: manifestYaml,
        prompt_markdown: promptMd,
      })
      setDetail(res.skill)
      toast(`已保存 ${detail.name}（落盘至 skills_custom/ 覆盖层，内置原件受保护）`)
      await loadSkills()
      await onRefresh()
    } catch (e: any) {
      toast('保存失败: ' + e.message)
    }
  }

  const createNewSkill = async () => {
    try {
      const res = await api<{ skill: any }>('/api/skills/create', 'POST', newSkill)
      setShowCreate(false)
      toast(`已新建自定义 Skill：${res.skill.name}`)
      await loadSkills()
      await selectSkill(res.skill.name)
      await onRefresh()
    } catch (e: any) {
      toast('新建失败: ' + e.message)
    }
  }

  const forkCurrent = async () => {
    if (!detail) return
    const nextName = window.prompt('输入新 Skill 名称（格式 group/slug）:', `${detail.name}-custom`)
    if (!nextName) return
    try {
      const res = await api<{ skill: any }>('/api/skills/fork', 'POST', {
        source_name: detail.name,
        new_name: nextName.trim(),
      })
      toast(`已复制为 ${res.skill.name}`)
      await loadSkills()
      await selectSkill(res.skill.name)
    } catch (e: any) {
      toast('复制失败: ' + e.message)
    }
  }

  const resetOrDelete = async () => {
    if (!detail) return
    const label = detail.can_reset ? '恢复为内置默认版本' : '删除该自定义 Skill'
    if (!window.confirm(`确定要${label}（${detail.name}）吗？`)) return
    try {
      const res = await api<{ action: string }>('/api/skills/reset', 'POST', { name: detail.name })
      toast(res.action === 'reset_to_builtin' ? '已恢复内置版本' : '已删除自定义 Skill')
      await loadSkills()
      if (res.action === 'reset_to_builtin') {
        await selectSkill(detail.name)
      } else {
        setDetail(null)
        setSelectedName('')
      }
      await onRefresh()
    } catch (e: any) {
      toast('操作失败: ' + e.message)
    }
  }

  const importMarkdownFile = (file: File) => {
    const reader = new FileReader()
    reader.onload = () => {
      const content = String(reader.result || '')
      const slug = file.name.replace(/\.md$/i, '').toLowerCase().replace(/[^a-z0-9_-]+/g, '-')
      setNewSkill((prev) => ({
        ...prev,
        name: `audit/${slug || 'imported-skill'}`,
        prompt_markdown: content,
      }))
      setShowCreate(true)
    }
    reader.readAsText(file)
  }

  const filtered = skills.filter(
    (s) =>
      s.name.toLowerCase().includes(query.toLowerCase()) ||
      s.description.toLowerCase().includes(query.toLowerCase()) ||
      s.stage.toLowerCase().includes(query.toLowerCase()),
  )

  return (
    <div className="grid h-full grid-cols-[290px_1fr] overflow-hidden">
      {/* Left Skill List */}
      <div className="flex flex-col overflow-hidden border-r border-[var(--border)] bg-[var(--surface)]">
        <div className="border-b border-[var(--border)] p-3">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-sm font-bold">Skill 管理中心</span>
            <div className="flex gap-1">
              <label className="flex cursor-pointer items-center gap-1 rounded-md border border-[var(--border)] bg-[var(--surface-2)] px-2 py-1 text-xs hover:border-sky-400">
                <Upload className="h-3.5 w-3.5" /> 导入
                <input
                  type="file"
                  accept=".md,.txt"
                  className="hidden"
                  onChange={(e) => {
                    const f = e.target.files?.[0]
                    if (f) importMarkdownFile(f)
                  }}
                />
              </label>
              <button
                onClick={() => setShowCreate(true)}
                className="flex items-center gap-1 rounded-md bg-sky-500 px-2 py-1 text-xs font-medium text-white hover:bg-sky-400"
              >
                <Plus className="h-3.5 w-3.5" /> 新建
              </button>
            </div>
          </div>
          <div className="flex items-center gap-2 rounded-lg border border-[var(--border)] bg-[var(--bg)] px-2.5 py-1.5">
            <Search className="h-3.5 w-3.5 text-[var(--muted)]" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="搜索 Skill 名称或阶段..."
              className="w-full bg-transparent text-xs outline-none"
            />
          </div>
        </div>

        <div className="flex-1 space-y-1 overflow-y-auto p-2">
          {filtered.map((s) => (
            <button
              key={s.name}
              onClick={() => selectSkill(s.name)}
              className={`w-full rounded-xl border px-3 py-2 text-left transition ${
                selectedName === s.name
                  ? 'border-sky-500/60 bg-sky-500/15'
                  : 'border-transparent hover:bg-[var(--surface-2)]'
              }`}
            >
              <div className="flex items-center justify-between gap-1">
                <span className="truncate text-xs font-semibold">{s.name}</span>
                <span
                  className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${
                    s.source === 'custom'
                      ? 'bg-purple-500/20 text-purple-300'
                      : s.source === 'override'
                        ? 'bg-amber-500/20 text-amber-300'
                        : 'bg-slate-600/30 text-[var(--muted)]'
                  }`}
                >
                  {s.source === 'custom' ? '自定义' : s.source === 'override' ? '已定制' : '内置'}
                </span>
              </div>
              <div className="mt-0.5 line-clamp-2 text-[11px] text-[var(--muted)]">{s.description}</div>
            </button>
          ))}
        </div>
      </div>

      {/* Right Preview / Split Editor */}
      <div className="flex flex-col overflow-hidden bg-[var(--bg)]">
        {!detail ? (
          <div className="flex flex-1 items-center justify-center text-sm text-[var(--muted)]">
            请在左侧选择一个 Skill 预览或编辑
          </div>
        ) : (
          <>
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--border)] bg-[var(--surface)] px-5 py-3">
              <div>
                <div className="flex items-center gap-2">
                  <strong className="text-sm">{detail.name}</strong>
                  <span className="rounded bg-sky-500/15 px-2 py-0.5 font-mono text-[11px] text-sky-400">
                    stage: {detail.stage}
                  </span>
                </div>
                <div className="text-xs text-[var(--muted)]">{detail.description}</div>
              </div>
              <div className="flex items-center gap-1.5">
                <div className="flex rounded-lg border border-[var(--border)] bg-[var(--bg)] p-0.5 text-xs">
                  {[
                    ['preview', '预览', Eye],
                    ['split', '分屏', SplitSquareHorizontal],
                    ['edit', '源码', FileCode2],
                  ].map(([m, lbl, Icon]: any) => (
                    <button
                      key={m}
                      onClick={() => setViewMode(m)}
                      className={`flex items-center gap-1 rounded-md px-2.5 py-1 ${
                        viewMode === m ? 'bg-sky-500/20 text-sky-400' : 'text-[var(--muted)]'
                      }`}
                    >
                      <Icon className="h-3.5 w-3.5" /> {lbl}
                    </button>
                  ))}
                </div>
                <button
                  onClick={forkCurrent}
                  className="flex items-center gap-1 rounded-lg border border-[var(--border)] bg-[var(--surface-2)] px-2.5 py-1.5 text-xs hover:border-sky-400"
                >
                  <CopyPlus className="h-3.5 w-3.5" /> 复制
                </button>
                {(detail.can_reset || detail.can_delete) && (
                  <button
                    onClick={resetOrDelete}
                    className="flex items-center gap-1 rounded-lg border border-rose-500/40 bg-rose-500/10 px-2.5 py-1.5 text-xs text-rose-400 hover:bg-rose-500/20"
                  >
                    {detail.can_reset ? <RotateCcw className="h-3.5 w-3.5" /> : <Trash2 className="h-3.5 w-3.5" />}
                    {detail.can_reset ? '恢复内置' : '删除'}
                  </button>
                )}
                <button
                  onClick={saveSkill}
                  className="flex items-center gap-1 rounded-lg bg-emerald-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-emerald-500"
                >
                  <Save className="h-3.5 w-3.5" /> 保存更改
                </button>
              </div>
            </div>

            <div className="flex flex-1 overflow-hidden">
              {(viewMode === 'edit' || viewMode === 'split') && (
                <div className="flex flex-1 flex-col gap-3 overflow-y-auto border-r border-[var(--border)] p-4">
                  <div>
                    <div className="mb-1 text-xs font-semibold text-[var(--muted)]">SKILL.md（Agent 操作指令正文）</div>
                    <textarea
                      value={promptMd}
                      onChange={(e) => setPromptMd(e.target.value)}
                      className="min-h-[340px] w-full rounded-xl border border-[var(--border)] bg-[var(--surface)] p-3 font-mono text-xs leading-relaxed outline-none focus:border-sky-500"
                    />
                  </div>
                  <div>
                    <div className="mb-1 text-xs font-semibold text-[var(--muted)]">skill.yaml（元信息与契约声明）</div>
                    <textarea
                      value={manifestYaml}
                      onChange={(e) => setManifestYaml(e.target.value)}
                      className="min-h-[150px] w-full rounded-xl border border-[var(--border)] bg-[var(--surface)] p-3 font-mono text-xs outline-none focus:border-sky-500"
                    />
                  </div>
                </div>
              )}

              {(viewMode === 'preview' || viewMode === 'split') && (
                <div className="flex-1 overflow-y-auto p-6">
                  <div className="mb-3 flex flex-wrap gap-1.5 text-[11px]">
                    <span className="rounded bg-[var(--surface-2)] px-2 py-0.5 text-[var(--muted)]">
                      输入: {(detail.inputs || []).join(', ') || '无'}
                    </span>
                    <span className="rounded bg-[var(--surface-2)] px-2 py-0.5 text-[var(--muted)]">
                      输出: {(detail.outputs || []).join(', ') || '无'}
                    </span>
                  </div>
                  <div
                    className="md-prose rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-6 text-sm"
                    dangerouslySetInnerHTML={{ __html: renderMarkdown(promptMd) }}
                  />
                </div>
              )}
            </div>
          </>
        )}
      </div>

      {/* Create Skill Modal */}
      {showCreate && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
          <div className="w-full max-w-xl rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-5 shadow-2xl">
            <h2 className="text-base font-bold">新建自定义 Skill</h2>
            <div className="mt-4 space-y-3 text-xs">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="mb-1 block font-semibold">名称（group/slug）</label>
                  <input
                    value={newSkill.name}
                    onChange={(e) => setNewSkill({ ...newSkill, name: e.target.value })}
                    className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2"
                  />
                </div>
                <div>
                  <label className="mb-1 block font-semibold">所属阶段</label>
                  <select
                    value={newSkill.stage}
                    onChange={(e) => setNewSkill({ ...newSkill, stage: e.target.value })}
                    className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2"
                  >
                    <option value="scout">scout（找项目）</option>
                    <option value="triage_project">triage_project（项目预评判）</option>
                    <option value="surface_map">surface_map（安全面测绘）</option>
                    <option value="deep_audit">deep_audit（深度源码审计）</option>
                    <option value="triage_vuln">triage_vuln（漏洞预评判）</option>
                    <option value="verify">verify（隔离验证）</option>
                    <option value="report">report（CNVD 报告写作）</option>
                  </select>
                </div>
              </div>
              <div>
                <label className="mb-1 block font-semibold">简介</label>
                <input
                  value={newSkill.description}
                  onChange={(e) => setNewSkill({ ...newSkill, description: e.target.value })}
                  className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2"
                />
              </div>
              <div>
                <label className="mb-1 block font-semibold">SKILL.md 正文</label>
                <textarea
                  value={newSkill.prompt_markdown}
                  onChange={(e) => setNewSkill({ ...newSkill, prompt_markdown: e.target.value })}
                  className="min-h-[200px] w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] p-3 font-mono"
                />
              </div>
            </div>
            <div className="mt-4 flex justify-end gap-2">
              <button
                onClick={() => setShowCreate(false)}
                className="rounded-lg border border-[var(--border)] px-3.5 py-1.5 text-xs"
              >
                取消
              </button>
              <button
                onClick={createNewSkill}
                className="rounded-lg bg-sky-500 px-4 py-1.5 text-xs font-semibold text-white hover:bg-sky-400"
              >
                创建 Skill
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
