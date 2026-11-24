import { marked } from 'marked'

export async function api<T = any>(url: string, method = 'GET', body?: unknown): Promise<T> {
  const opts: RequestInit = {
    method,
    headers: { 'Content-Type': 'application/json' },
  }
  if (body !== undefined) {
    opts.body = JSON.stringify(body)
  }
  const res = await fetch(url, opts)
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    throw new Error(data.detail || data.error || `HTTP ${res.status}`)
  }
  return data as T
}

export async function streamChatMessage(
  sessionId: string,
  message: string,
  onEvent: (ev: any) => void,
): Promise<void> {
  const res = await fetch(`/api/chat/sessions/${encodeURIComponent(sessionId)}/send`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message }),
  })
  if (!res.ok || !res.body) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || `HTTP ${res.status}`)
  }
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    const parts = buf.split('\n\n')
    buf = parts.pop() || ''
    for (const chunk of parts) {
      for (const line of chunk.split('\n')) {
        if (line.startsWith('data: ')) {
          try {
            onEvent(JSON.parse(line.slice(6)))
          } catch {
            // ignore malformed frame
          }
        }
      }
    }
  }
}

export function renderMarkdown(md: string): string {
  return marked.parse(md || '', { async: false }) as string
}

export const CAPABILITY_LABELS: Record<string, string> = {
  deep_reasoning: '深度代码推理',
  docker_verify: '容器与工程验证',
  bulk_triage: '低成本批量初筛',
  cn_writing: '中文报告写作',
  tool_use: '工具与终端操控',
  long_context: '超长上下文',
}

export const STAGE_META: Record<string, { label: string; role: string; desc: string }> = {
  scout: { label: '项目发现', role: '侦察员', desc: '多平台发现/导入仓库与去重' },
  triage_project: { label: '项目预评判', role: '项目预审官', desc: '热度、部署度与重复风险打分' },
  surface_map: { label: '安全面测绘', role: '测绘工程师', desc: '框架、权限边界与路由提取' },
  deep_audit: { label: '深度源码审计', role: '主审研究员', desc: '多视角并行源码追踪与调用链' },
  triage_vuln: { label: '异构复核', role: '异构复核官', desc: '跨模型去误报与历史 CVE 去重' },
  verify: { label: '隔离环境验证', role: '验证工程师', desc: '官方 Docker 部署、代理与熔断' },
  evidence: { label: '自动出图', role: '确定性渲染器', desc: '代码/Web/HTTP/终端四类高清图' },
  report: { label: 'CNVD 报告', role: 'CNVD 报告主笔', desc: '去人机感 Word 与提报表单双输出' },
}
