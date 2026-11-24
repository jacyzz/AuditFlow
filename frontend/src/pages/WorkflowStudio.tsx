import { memo, useCallback, useEffect, useMemo, useState } from 'react'
import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  MarkerType,
  MiniMap,
  Position,
  ReactFlow,
  useEdgesState,
  useNodesState,
  type Edge,
  type Node,
  type NodeProps,
} from '@xyflow/react'
import {
  AlertTriangle,
  Check,
  CheckCircle2,
  RotateCcw,
  Save,
  ShieldAlert,
  Sparkles,
} from 'lucide-react'
import { api } from '../api'
import { AgentIcon } from '../components/AgentIcon'
import { Button, Field, Input, SegmentedControl, Select, StatusPill, cn } from '../components/ui'

interface Props {
  overview: any
  onRefresh: () => Promise<void>
  toast: (msg: string) => void
  dark: boolean
}

const STAGE_META = [
  { key: 'scout', step: '01', title: '找项目 · Scout', subtitle: '仓库发现与去重', pos: { x: 40, y: 60 } },
  { key: 'triage_project', step: '02', title: '项目预判', subtitle: 'CNVD 价值与红海评估', pos: { x: 320, y: 60 } },
  { key: 'surface_map', step: '03', title: '安全面测绘', subtitle: '路由、鉴权与高危入口', pos: { x: 760, y: 60 } },
  { key: 'deep_audit', step: '04', title: '深度源码审计', subtitle: '多子 Skill 并行审计', pos: { x: 1040, y: 60 } },
  { key: 'triage_vuln', step: '05', title: '异构漏洞复核', subtitle: '交叉验证去误报', pos: { x: 40, y: 270 } },
  { key: 'verify', step: '06', title: '隔离验证', subtitle: '官方 Docker + 代理熔断', pos: { x: 480, y: 270 } },
  { key: 'evidence', step: '07', title: '确定性出图', subtitle: '代码 / Web / HTTP / 终端', pos: { x: 760, y: 270 } },
  { key: 'report', step: '08', title: 'CNVD 双输出', subtitle: '.docx 报告 + 提报表单', pos: { x: 1040, y: 270 } },
] as const

const ALL_RENDERERS = ['code', 'web', 'http', 'term']

type StageNodeData = {
  step: string
  stageKey: string
  title: string
  subtitle: string
  adapter: string
  adapterDisplay: string
  backend: string
  skillSummary: string
  selected: boolean
  dark: boolean
  warning?: string
}

type GateNodeData = {
  label: string
  sublabel: string
  pendingCount: number
}

const StageNode = memo(function StageNode({ data }: NodeProps<Node<StageNodeData>>) {
  return (
    <div
      className={cn(
        'w-[232px] rounded-[12px] border bg-[var(--surface)] p-3 text-left transition-all duration-150',
        data.selected
          ? 'border-[var(--primary)] ring-2 ring-[var(--primary)]/18 shadow-[var(--shadow-sm)]'
          : 'border-[var(--border)] shadow-[var(--shadow-xs)] hover:border-[var(--border-strong)]',
      )}
    >
      <Handle
        type="target"
        position={Position.Left}
        className="!h-2 !w-2 !border-[var(--surface)] !bg-[var(--border-strong)]"
      />
      <Handle
        type="source"
        position={Position.Right}
        className="!h-2 !w-2 !border-[var(--surface)] !bg-[var(--border-strong)]"
      />

      <div className="flex items-center justify-between gap-2">
        <span className="font-mono text-[10.5px] font-semibold text-[var(--muted)]">
          STEP {data.step}
        </span>
        <span className="rounded-md bg-[var(--control-bg)] px-1.5 py-0.5 font-mono text-[10px] text-[var(--muted)]">
          {data.backend}
        </span>
      </div>

      <div className="mt-1.5 text-[13.5px] font-semibold text-[var(--fg)]">{data.title}</div>
      <div className="text-[11px] text-[var(--muted)]">{data.subtitle}</div>

      <div className="mt-2.5 flex items-center justify-between gap-2 border-t border-[var(--border)] pt-2">
        {data.stageKey === 'evidence' ? (
          <span className="text-[11.5px] font-medium text-[var(--fg-secondary)]">
            内置确定性渲染器
          </span>
        ) : (
          <div className="flex min-w-0 items-center gap-1.5">
            <AgentIcon agent={data.adapter} dark={data.dark} size={15} />
            <span className="truncate text-[12px] font-medium text-[var(--fg)]">
              {data.adapterDisplay}
            </span>
          </div>
        )}
        {data.warning && (
          <span title={data.warning} className="text-[var(--warn)]">
            <AlertTriangle className="h-3.5 w-3.5" />
          </span>
        )}
      </div>

      <div className="mt-1 truncate font-mono text-[10.5px] text-[var(--subtle)]">
        {data.skillSummary}
      </div>
    </div>
  )
})

const GateNode = memo(function GateNode({ data }: NodeProps<Node<GateNodeData>>) {
  return (
    <div className="w-[144px] rounded-[12px] border border-[var(--warn-border)] bg-[var(--warn-bg)] px-3 py-2.5 text-center backdrop-blur-[2px]">
      <Handle
        type="target"
        position={Position.Left}
        className="!h-2 !w-2 !border-[var(--surface)] !bg-[var(--warn)]"
      />
      <Handle
        type="source"
        position={Position.Right}
        className="!h-2 !w-2 !border-[var(--surface)] !bg-[var(--warn)]"
      />
      <div className="flex items-center justify-center gap-1 text-[11.5px] font-semibold text-[var(--warn)]">
        <ShieldAlert className="h-3.5 w-3.5" />
        <span>{data.label}</span>
      </div>
      <div className="mt-0.5 text-[10.5px] text-[var(--fg-secondary)]">{data.sublabel}</div>
      {data.pendingCount > 0 && (
        <div className="mt-1 inline-block rounded-full bg-[var(--warn)] px-1.5 py-0.5 text-[10px] font-semibold text-white">
          {data.pendingCount} 待审批
        </div>
      )}
    </div>
  )
})

const nodeTypes = { stageNode: StageNode, gateNode: GateNode }

export default function WorkflowStudio({ overview, onRefresh, toast, dark }: Props) {
  const [stages, setStages] = useState<Record<string, any>>({})
  const [profiles, setProfiles] = useState<any[]>([])
  const [recommendations, setRecommendations] = useState<Record<string, any>>({})
  const [skillsByStage, setSkillsByStage] = useState<
    Record<string, { name: string; description: string }[]>
  >({})
  const [selectedKey, setSelectedKey] = useState<string>('deep_audit')
  const [saving, setSaving] = useState(false)

  const load = async () => {
    try {
      const [cfg, prof, disc] = await Promise.all([
        api<any>('/api/config'),
        api<any>('/api/agents/profiles'),
        api<any>('/api/discover-agents'),
      ])
      setStages(cfg.pipeline?.stages || {})
      setProfiles(prof.profiles || [])
      setRecommendations(prof.recommendations || {})
      const rawMap = disc.skills_by_stage || {}
      const norm: Record<string, { name: string; description: string }[]> = {}
      for (const [stage, items] of Object.entries(rawMap)) {
        norm[stage] = (Array.isArray(items) ? items : []).map((it: any) =>
          typeof it === 'string'
            ? { name: it, description: '' }
            : { name: String(it?.name || ''), description: String(it?.description || '') },
        )
      }
      setSkillsByStage(norm)
    } catch (e: any) {
      toast('加载编排配置失败: ' + e.message)
    }
  }

  useEffect(() => {
    load()
  }, [])

  const profileMap = useMemo(() => {
    const m: Record<string, any> = {}
    for (const p of profiles) m[p.name] = p
    return m
  }, [profiles])

  const deepAdapter = stages.deep_audit?.adapter
  const triageAdapter = stages.triage_vuln?.adapter
  const isHeterogeneous = Boolean(deepAdapter && triageAdapter && deepAdapter !== triageAdapter)

  const initialNodes = useMemo<Node[]>(() => {
    const stageNodes: Node<StageNodeData>[] = STAGE_META.map((m) => {
      const st = stages[m.key] || {}
      const adapterName = st.adapter || (m.key === 'evidence' ? 'deterministic' : 'native-subagent')
      const skillSummary =
        m.key === 'evidence'
          ? (st.renderers || ALL_RENDERERS).join(' · ')
          : Array.isArray(st.skills)
            ? st.skills.join(', ')
            : st.skill || '未指定 Skill'
      return {
        id: m.key,
        type: 'stageNode',
        position: m.pos,
        data: {
          step: m.step,
          stageKey: m.key,
          title: m.title,
          subtitle: m.subtitle,
          adapter: adapterName,
          adapterDisplay: profileMap[adapterName]?.display_name || adapterName,
          backend: st.backend || 'local',
          skillSummary,
          selected: selectedKey === m.key,
          dark,
          warning:
            m.key === 'triage_vuln' && !isHeterogeneous
              ? '当前与深度审计同模型，建议异构互审'
              : undefined,
        },
      }
    })

    const gateNodes: Node<GateNodeData>[] = [
      {
        id: 'gate1',
        type: 'gateNode',
        position: { x: 584, y: 84 },
        data: {
          label: 'Gate 1',
          sublabel: '人工勾选项目',
          pendingCount: overview?.counts?.gate1_pending || 0,
        },
      },
      {
        id: 'gate2',
        type: 'gateNode',
        position: { x: 304, y: 294 },
        data: {
          label: 'Gate 2',
          sublabel: '人工放行验证',
          pendingCount: overview?.counts?.gate2_pending || 0,
        },
      },
    ]

    return [...stageNodes, ...gateNodes]
  }, [stages, profileMap, selectedKey, dark, isHeterogeneous, overview])

  const initialEdges = useMemo<Edge[]>(() => {
    const color = dark ? '#525252' : '#b5b5b5'
    const mk = (source: string, target: string, animated = false): Edge => ({
      id: `${source}->${target}`,
      source,
      target,
      type: 'smoothstep',
      animated,
      style: { stroke: color, strokeWidth: 1.6 },
      markerEnd: { type: MarkerType.ArrowClosed, color, width: 15, height: 15 },
    })
    return [
      mk('scout', 'triage_project'),
      mk('triage_project', 'gate1'),
      mk('gate1', 'surface_map', true),
      mk('surface_map', 'deep_audit'),
      mk('deep_audit', 'triage_vuln'),
      mk('triage_vuln', 'gate2'),
      mk('gate2', 'verify', true),
      mk('verify', 'evidence'),
      mk('evidence', 'report'),
    ]
  }, [dark])

  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes)
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges)

  useEffect(() => {
    setNodes((prev) => {
      const posById = new Map(prev.map((n) => [n.id, n.position]))
      return initialNodes.map((n) => ({
        ...n,
        position: posById.get(n.id) || n.position,
      }))
    })
  }, [initialNodes, setNodes])

  useEffect(() => {
    setEdges(initialEdges)
  }, [initialEdges, setEdges])

  const resetLayout = () => {
    setNodes(initialNodes)
  }

  const onNodeClick = useCallback((_: any, node: Node) => {
    if (node.type === 'stageNode') {
      setSelectedKey(node.id)
    }
  }, [])

  const patchStage = (key: string, patch: Record<string, any>) => {
    setStages((prev) => ({ ...prev, [key]: { ...(prev[key] || {}), ...patch } }))
  }

  const applyRecommended = () => {
    const next = { ...stages }
    for (const [k, rec] of Object.entries(recommendations)) {
      if (k === 'evidence') continue
      next[k] = {
        ...(next[k] || {}),
        adapter: rec.adapter,
        backend: rec.backend || next[k]?.backend || 'local',
      }
    }
    setStages(next)
    toast('已按 Agent 能力强项与异构互审原则预填方案，点击「保存编排」写入 pipeline.yaml')
  }

  const saveWorkflow = async () => {
    setSaving(true)
    try {
      await api('/api/config/apply-visual', 'POST', { stages })
      toast('流水线编排已校验并写入 config/pipeline.yaml')
      await onRefresh()
    } catch (e: any) {
      toast('保存编排失败: ' + e.message)
    } finally {
      setSaving(false)
    }
  }

  const curMeta = STAGE_META.find((m) => m.key === selectedKey) || STAGE_META[0]
  const curStage = stages[selectedKey] || {}
  const curSkills = skillsByStage[selectedKey] || []
  const curRec = recommendations[selectedKey]

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Compact Tahoe Toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--border)] px-5 py-3">
        <div className="flex items-center gap-3">
          <div>
            <h1 className="text-[15.5px] font-semibold tracking-[-0.015em]">可视化编排画布</h1>
            <p className="text-[11.5px] text-[var(--muted)]">
              拖拽、缩放并点击任意节点，实时热替换该阶段的 Agent、Skill 与执行后端
            </p>
          </div>
          {isHeterogeneous ? (
            <StatusPill tone="ok" dot>
              <CheckCircle2 className="h-3 w-3" />
              异构互审已生效（{deepAdapter} ⇄ {triageAdapter}）
            </StatusPill>
          ) : (
            <StatusPill tone="warn" dot>
              建议深审与复核使用不同 Agent（当前均为 {deepAdapter || '未设置'}）
            </StatusPill>
          )}
        </div>

        <div className="flex items-center gap-2">
          <Button variant="ghost" onClick={resetLayout}>
            <RotateCcw className="h-3.5 w-3.5" /> 重置布局
          </Button>
          <Button variant="secondary" onClick={applyRecommended}>
            <Sparkles className="h-3.5 w-3.5" /> 按强项一键分配
          </Button>
          <Button variant="primary" disabled={saving} onClick={saveWorkflow}>
            <Save className="h-3.5 w-3.5" /> {saving ? '保存中...' : '保存编排'}
          </Button>
        </div>
      </div>

      {/* Main Split: React Flow Canvas + Right Node Inspector */}
      <div className="flex flex-1 overflow-hidden">
        <div className="relative flex-1 bg-[var(--surface-subtle)]">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onNodeClick={onNodeClick}
            nodeTypes={nodeTypes}
            fitView
            fitViewOptions={{ padding: 0.16 }}
            minZoom={0.45}
            maxZoom={1.5}
          >
            <Background
              variant={BackgroundVariant.Dots}
              gap={18}
              size={1.2}
              color="var(--canvas-dot)"
            />
            <Controls showInteractive={false} />
            <MiniMap
              nodeColor={(n) => (n.type === 'gateNode' ? '#f2ae49' : dark ? '#404040' : '#d4d4d4')}
              maskColor={dark ? 'rgba(0,0,0,0.45)' : 'rgba(244,244,244,0.65)'}
              pannable
              zoomable
            />
          </ReactFlow>
        </div>

        {/* Right Node Inspector */}
        <aside className="flex w-[348px] shrink-0 flex-col border-l border-[var(--border)] bg-[var(--surface)]">
          <div className="border-b border-[var(--border)] px-5 py-3.5">
            <div className="flex items-center justify-between">
              <span className="font-mono text-[11px] font-semibold text-[var(--muted)]">
                STEP {curMeta.step} · {curMeta.key}
              </span>
              <StatusPill tone="neutral">{curStage.backend || 'local'}</StatusPill>
            </div>
            <h2 className="mt-1 text-[15px] font-semibold">{curMeta.title}</h2>
            <p className="mt-0.5 text-xs text-[var(--muted)]">{curMeta.subtitle}</p>
          </div>

          <div className="flex-1 space-y-5 overflow-y-auto p-5">
            {/* Recommendation Hint */}
            {curRec && selectedKey !== 'evidence' && (
              <div className="rounded-[10px] border border-[var(--border)] bg-[var(--surface-subtle)] p-3 text-xs">
                <div className="flex items-center justify-between">
                  <span className="font-medium text-[var(--fg)]">强项推荐</span>
                  <button
                    type="button"
                    onClick={() =>
                      patchStage(selectedKey, {
                        adapter: curRec.adapter,
                        backend: curRec.backend || curStage.backend || 'local',
                      })
                    }
                    className="text-[11px] font-medium text-[var(--fg)] underline underline-offset-2 hover:opacity-75 cursor-pointer"
                  >
                    一键采纳
                  </button>
                </div>
                <div className="mt-1 flex items-center gap-1.5 font-medium">
                  <AgentIcon agent={curRec.adapter} dark={dark} size={14} />
                  <span>{curRec.display_name}</span>
                </div>
                <p className="mt-1 text-[11.5px] leading-relaxed text-[var(--muted)]">
                  {curRec.reason}
                </p>
              </div>
            )}

            {/* Agent Picker */}
            {selectedKey !== 'evidence' && (
              <div className="space-y-2">
                <div className="text-xs font-medium text-[var(--fg-secondary)]">负责 Agent</div>
                <div className="tahoe-card divide-y divide-[var(--border)] overflow-hidden">
                  {profiles.map((p) => {
                    const active = curStage.adapter === p.name
                    return (
                      <button
                        key={p.name}
                        type="button"
                        onClick={() => patchStage(selectedKey, { adapter: p.name })}
                        className={cn(
                          'flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-xs transition-colors cursor-pointer',
                          active
                            ? 'bg-[var(--surface-active)] font-medium text-[var(--fg)]'
                            : 'hover:bg-[var(--surface-hover)] text-[var(--fg-secondary)]',
                        )}
                      >
                        <span className="flex min-w-0 items-center gap-2">
                          <AgentIcon agent={p.name} dark={dark} size={16} />
                          <span className="truncate">{p.display_name}</span>
                        </span>
                        <span className="flex shrink-0 items-center gap-1.5 whitespace-nowrap">
                          {!p.detected && (
                            <span className="text-[10px] text-[var(--subtle)]">未就绪</span>
                          )}
                          {active && <Check className="h-3.5 w-3.5 text-[var(--fg)]" />}
                        </span>
                      </button>
                    )
                  })}
                </div>
              </div>
            )}

            {/* Skill / Renderers Selector */}
            {selectedKey === 'evidence' ? (
              <div className="space-y-2">
                <div className="text-xs font-medium text-[var(--fg-secondary)]">启用的确定性渲染器</div>
                <div className="grid grid-cols-2 gap-2">
                  {ALL_RENDERERS.map((r) => {
                    const list: string[] = curStage.renderers || ALL_RENDERERS
                    const checked = list.includes(r)
                    return (
                      <button
                        key={r}
                        type="button"
                        onClick={() => {
                          const next = checked ? list.filter((x) => x !== r) : [...list, r]
                          if (next.length > 0) patchStage('evidence', { renderers: next })
                        }}
                        className={cn(
                          'flex items-center justify-between rounded-[10px] border px-3 py-2 font-mono text-xs cursor-pointer',
                          checked
                            ? 'border-[var(--primary)] bg-[var(--surface-subtle)] font-medium'
                            : 'border-[var(--border)] text-[var(--muted)]',
                        )}
                      >
                        <span>{r}</span>
                        {checked && <Check className="h-3.5 w-3.5" />}
                      </button>
                    )
                  })}
                </div>
              </div>
            ) : selectedKey === 'deep_audit' ? (
              <div className="space-y-2">
                <div className="text-xs font-medium text-[var(--fg-secondary)]">
                  并行审计子 Skill（多选）
                </div>
                <div className="tahoe-card divide-y divide-[var(--border)] overflow-hidden">
                  {curSkills.map((sk) => {
                    const list: string[] = curStage.skills || []
                    const checked = list.includes(sk.name)
                    return (
                      <button
                        key={sk.name}
                        type="button"
                        onClick={() => {
                          const next = checked
                            ? list.filter((x) => x !== sk.name)
                            : [...list, sk.name]
                          if (next.length > 0) patchStage('deep_audit', { skills: next })
                        }}
                        className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left hover:bg-[var(--surface-hover)] cursor-pointer"
                      >
                        <div className="min-w-0">
                          <div
                            className={cn(
                              'truncate font-mono text-xs',
                              checked ? 'font-medium text-[var(--fg)]' : 'text-[var(--muted)]',
                            )}
                          >
                            {sk.name}
                          </div>
                          {sk.description && (
                            <div className="truncate text-[10.5px] text-[var(--subtle)]">
                              {sk.description}
                            </div>
                          )}
                        </div>
                        <span
                          className={cn(
                            'flex h-4 w-4 shrink-0 items-center justify-center rounded-full border',
                            checked
                              ? 'border-[var(--primary)] bg-[var(--primary)] text-[var(--primary-fg)]'
                              : 'border-[var(--border-strong)]',
                          )}
                        >
                          {checked && <Check className="h-2.5 w-2.5 stroke-[3]" />}
                        </span>
                      </button>
                    )
                  })}
                </div>
              </div>
            ) : (
              <Field label="绑定 Skill 模板">
                <Select
                  value={curStage.skill || ''}
                  onChange={(e) => patchStage(selectedKey, { skill: e.target.value })}
                >
                  {curSkills.map((sk) => (
                    <option key={sk.name} value={sk.name}>
                      {sk.name}
                    </option>
                  ))}
                </Select>
              </Field>
            )}

            {/* Execution Backend */}
            <Field label="执行后端">
              <SegmentedControl
                className="w-full justify-between"
                value={curStage.backend || 'local'}
                onChange={(v) => patchStage(selectedKey, { backend: v })}
                options={[
                  { value: 'local', label: 'local' },
                  { value: 'ssh-ubuntu', label: 'ssh-ubuntu' },
                  { value: 'wsl2', label: 'wsl2' },
                ]}
              />
            </Field>

            {/* Timeout */}
            {selectedKey !== 'evidence' && (
              <Field label="单阶段超时（秒）">
                <Input
                  type="number"
                  value={curStage.timeout_sec ?? 600}
                  onChange={(e) =>
                    patchStage(selectedKey, { timeout_sec: Math.max(30, Number(e.target.value) || 600) })
                  }
                />
              </Field>
            )}
          </div>
        </aside>
      </div>
    </div>
  )
}
