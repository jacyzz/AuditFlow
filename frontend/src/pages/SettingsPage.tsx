import { useEffect, useState } from 'react'
import CodeMirror from '@uiw/react-codemirror'
import { yaml } from '@codemirror/lang-yaml'
import { oneDark } from '@codemirror/theme-one-dark'
import { Code2, Save, SlidersHorizontal } from 'lucide-react'
import { api } from '../api'
import { Button, Field, Input, SegmentedControl, Switch } from '../components/ui'

interface Props {
  toast: (msg: string) => void
  dark: boolean
}

export default function SettingsPage({ toast, dark }: Props) {
  const [envObj, setEnvObj] = useState<any>(null)
  const [envYaml, setEnvYaml] = useState('')
  const [mode, setMode] = useState<'form' | 'yaml'>('form')
  const [saving, setSaving] = useState(false)

  const load = async () => {
    try {
      const res = await api<any>('/api/config')
      setEnvObj(res.env)
      setEnvYaml(res.env_yaml)
    } catch (e: any) {
      toast('读取环境配置失败: ' + e.message)
    }
  }

  useEffect(() => {
    load()
  }, [])

  const save = async () => {
    setSaving(true)
    try {
      if (mode === 'form') {
        await api('/api/config/save', 'POST', { env_structured: envObj })
      } else {
        await api('/api/config/save', 'POST', { env_yaml: envYaml })
      }
      toast('已校验并保存 config/env.yaml')
      await load()
    } catch (e: any) {
      toast('保存失败: ' + e.message)
    } finally {
      setSaving(false)
    }
  }

  if (!envObj) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-[var(--muted)]">
        加载环境配置中...
      </div>
    )
  }

  const paths = envObj.paths || {}
  const excel = paths.excel_sync || { enabled: false, excel_path: '' }
  const ssh = envObj.backends?.['ssh-ubuntu'] || {
    host: 'Ubuntu2404',
    workspace_root: '/home/wood/audit-pipeline/workspaces',
    connect_timeout_sec: 15,
  }
  const wsl = envObj.backends?.wsl2 || {
    distro: 'Ubuntu-24.04',
    workspace_root: '/home/wood/audit-pipeline/workspaces',
  }
  const docker = envObj.docker_verify || {}

  const patchPath = (patch: Record<string, any>) =>
    setEnvObj({ ...envObj, paths: { ...paths, ...patch } })
  const patchExcel = (patch: Record<string, any>) =>
    patchPath({ excel_sync: { ...excel, ...patch } })
  const patchSsh = (patch: Record<string, any>) =>
    setEnvObj({ ...envObj, backends: { ...envObj.backends, 'ssh-ubuntu': { ...ssh, ...patch } } })
  const patchWsl = (patch: Record<string, any>) =>
    setEnvObj({ ...envObj, backends: { ...envObj.backends, wsl2: { ...wsl, ...patch } } })
  const patchDocker = (patch: Record<string, any>) =>
    setEnvObj({ ...envObj, docker_verify: { ...docker, ...patch } })

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div className="flex items-center justify-between border-b border-[var(--border)] px-6 py-3.5">
        <div>
          <h1 className="text-[16px] font-semibold tracking-[-0.015em]">环境与隔离沙箱设置</h1>
          <p className="mt-0.5 text-xs text-[var(--muted)]">
            管理 config/env.yaml 中的报告输出路径、Linux 远端主机、Docker 代理与隔离护栏
          </p>
        </div>
        <div className="flex items-center gap-2">
          <SegmentedControl
            value={mode}
            onChange={setMode}
            options={[
              { value: 'form', label: '分组表单', icon: <SlidersHorizontal className="h-3.5 w-3.5" /> },
              { value: 'yaml', label: 'YAML 源码', icon: <Code2 className="h-3.5 w-3.5" /> },
            ]}
          />
          <Button variant="primary" disabled={saving} onClick={save}>
            <Save className="h-3.5 w-3.5" /> {saving ? '保存中...' : '保存配置'}
          </Button>
        </div>
      </div>

      {mode === 'yaml' ? (
        <div className="flex-1 overflow-hidden">
          <CodeMirror
            value={envYaml}
            height="100%"
            theme={dark ? oneDark : 'light'}
            extensions={[yaml()]}
            onChange={setEnvYaml}
            basicSetup={{ lineNumbers: true, foldGutter: true }}
          />
        </div>
      ) : (
        <div className="flex-1 overflow-y-auto bg-[var(--surface-subtle)] p-6">
          <div className="mx-auto max-w-3xl space-y-6">
            {/* Group 1: Paths & Excel */}
            <section className="space-y-2">
              <div className="px-1 text-xs font-medium text-[var(--muted)]">报告输出与本地台账</div>
              <div className="tahoe-card space-y-4 p-5">
                <Field label="Word 报告与 CNVD 表单输出目录">
                  <Input
                    className="font-mono"
                    value={paths.windows_report_output_dir || ''}
                    onChange={(e) => patchPath({ windows_report_output_dir: e.target.value })}
                  />
                </Field>
                <Field label="SQLite 状态机与去重台账路径">
                  <Input
                    className="font-mono"
                    value={paths.tracker_db_path || ''}
                    onChange={(e) => patchPath({ tracker_db_path: e.target.value })}
                  />
                </Field>
                <div className="flex items-center justify-between border-t border-[var(--border)] pt-3">
                  <div>
                    <div className="text-xs font-medium">自动同步到汇总 Excel</div>
                    <div className="text-[11px] text-[var(--muted)]">
                      生成报告时自动备份原表并追加新记录
                    </div>
                  </div>
                  <Switch
                    checked={Boolean(excel.enabled)}
                    onChange={(v) => patchExcel({ enabled: v })}
                  />
                </div>
                {excel.enabled && (
                  <Field label="汇总 Excel 文件路径">
                    <Input
                      className="font-mono"
                      value={excel.excel_path || ''}
                      onChange={(e) => patchExcel({ excel_path: e.target.value })}
                    />
                  </Field>
                )}
              </div>
            </section>

            {/* Group 2: Remote Linux / WSL2 Backends */}
            <section className="space-y-2">
              <div className="px-1 text-xs font-medium text-[var(--muted)]">
                远端执行后端（SSH Ubuntu / WSL2）
              </div>
              <div className="tahoe-card divide-y divide-[var(--border)] overflow-hidden">
                <div className="grid gap-4 p-5 sm:grid-cols-2">
                  <Field label="SSH Host 别名" hint="对应 ~/.ssh/config">
                    <Input
                      className="font-mono"
                      value={ssh.host || ''}
                      onChange={(e) => patchSsh({ host: e.target.value })}
                    />
                  </Field>
                  <Field label="Ubuntu 工作区根目录">
                    <Input
                      className="font-mono"
                      value={ssh.workspace_root || ''}
                      onChange={(e) => patchSsh({ workspace_root: e.target.value })}
                    />
                  </Field>
                </div>
                <div className="grid gap-4 p-5 sm:grid-cols-2">
                  <Field label="WSL2 发行版名称">
                    <Input
                      className="font-mono"
                      value={wsl.distro || ''}
                      onChange={(e) => patchWsl({ distro: e.target.value })}
                    />
                  </Field>
                  <Field label="WSL2 工作区根目录">
                    <Input
                      className="font-mono"
                      value={wsl.workspace_root || ''}
                      onChange={(e) => patchWsl({ workspace_root: e.target.value })}
                    />
                  </Field>
                </div>
              </div>
            </section>

            {/* Group 3: Docker Verify & Guardrails */}
            <section className="space-y-2">
              <div className="px-1 text-xs font-medium text-[var(--muted)]">
                Docker 隔离验证、代理与可选 Burp 导流
              </div>
              <div className="tahoe-card space-y-4 p-5">
                <div className="grid gap-4 sm:grid-cols-2">
                  <Field label="HTTP 代理（拉取镜像/构建用）">
                    <Input
                      className="font-mono"
                      value={docker.http_proxy || ''}
                      onChange={(e) => patchDocker({ http_proxy: e.target.value })}
                      placeholder="http://127.0.0.1:7890"
                    />
                  </Field>
                  <Field label="HTTPS 代理">
                    <Input
                      className="font-mono"
                      value={docker.https_proxy || ''}
                      onChange={(e) => patchDocker({ https_proxy: e.target.value })}
                      placeholder="http://127.0.0.1:7890"
                    />
                  </Field>
                </div>
                <div className="grid gap-4 sm:grid-cols-3">
                  <Field label="可选 Burp 上游代理" hint="留空关闭">
                    <Input
                      className="font-mono"
                      value={docker.burp_upstream_proxy || ''}
                      onChange={(e) =>
                        patchDocker({ burp_upstream_proxy: e.target.value.trim() || null })
                      }
                      placeholder="http://127.0.0.1:8080"
                    />
                  </Field>
                  <Field label="启动超时（秒）">
                    <Input
                      type="number"
                      value={docker.startup_timeout_sec ?? 300}
                      onChange={(e) =>
                        patchDocker({ startup_timeout_sec: Number(e.target.value) || 300 })
                      }
                    />
                  </Field>
                  <Field label="部署最大重试次数">
                    <Input
                      type="number"
                      value={docker.max_retries ?? 2}
                      onChange={(e) => patchDocker({ max_retries: Number(e.target.value) || 2 })}
                    />
                  </Field>
                </div>
                <Field label="允许访问的隔离私网 CIDR（逗号分隔，仅限本地/内网靶机）">
                  <Input
                    className="font-mono"
                    value={(docker.allowed_target_cidrs || []).join(', ')}
                    onChange={(e) =>
                      patchDocker({
                        allowed_target_cidrs: e.target.value
                          .split(',')
                          .map((s) => s.trim())
                          .filter(Boolean),
                      })
                    }
                  />
                </Field>
              </div>
            </section>
          </div>
        </div>
      )}
    </div>
  )
}
