import { useEffect, useState } from 'react'
import { Code2, Save, SlidersHorizontal } from 'lucide-react'
import { api } from '../api'

interface Props {
  toast: (msg: string) => void
}

export default function SettingsPage({ toast }: Props) {
  const [envObj, setEnvObj] = useState<any>(null)
  const [envYaml, setEnvYaml] = useState('')
  const [rawMode, setRawMode] = useState(false)

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

  const saveStructured = async () => {
    try {
      await api('/api/config/save', 'POST', { env_structured: envObj })
      toast('已校验并保存 config/env.yaml')
      await load()
    } catch (e: any) {
      toast('保存失败: ' + e.message)
    }
  }

  const saveRaw = async () => {
    try {
      await api('/api/config/save', 'POST', { env_yaml: envYaml })
      toast('已保存原始 YAML 到 config/env.yaml')
      await load()
    } catch (e: any) {
      toast('YAML 校验失败: ' + e.message)
    }
  }

  if (!envObj) {
    return <div className="p-8 text-sm text-[var(--muted)]">加载配置中...</div>
  }

  const paths = envObj.paths || {}
  const ssh = envObj.backends?.['ssh-ubuntu'] || { host: 'Ubuntu2404', workspace_root: '/home/wood/audit-pipeline/workspaces', connect_timeout_sec: 15 }
  const wsl = envObj.backends?.wsl2 || { distro: 'Ubuntu-24.04', workspace_root: '/home/wood/audit-pipeline/workspaces' }
  const docker = envObj.docker_verify || {}

  const patchPath = (patch: Record<string, any>) =>
    setEnvObj({ ...envObj, paths: { ...paths, ...patch } })
  const patchSsh = (patch: Record<string, any>) =>
    setEnvObj({ ...envObj, backends: { ...envObj.backends, 'ssh-ubuntu': { ...ssh, ...patch } } })
  const patchWsl = (patch: Record<string, any>) =>
    setEnvObj({ ...envObj, backends: { ...envObj.backends, wsl2: { ...wsl, ...patch } } })
  const patchDocker = (patch: Record<string, any>) =>
    setEnvObj({ ...envObj, docker_verify: { ...docker, ...patch } })

  return (
    <div className="flex h-full flex-col overflow-hidden bg-[var(--bg)]">
      <div className="flex items-center justify-between border-b border-[var(--border)] bg-[var(--surface)] px-6 py-4">
        <div>
          <h1 className="text-lg font-bold">环境与隔离沙箱设置（env.yaml）</h1>
          <p className="text-xs text-[var(--muted)]">配置报告输出目录、Ubuntu SSH/WSL2 主机、Docker 代理端口与可选 Burp 导流</p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => setRawMode((v) => !v)}
            className="flex items-center gap-1.5 rounded-xl border border-[var(--border)] bg-[var(--surface-2)] px-3 py-2 text-xs"
          >
            {rawMode ? <SlidersHorizontal className="h-3.5 w-3.5" /> : <Code2 className="h-3.5 w-3.5" />}
            {rawMode ? '表单模式' : 'YAML 源码'}
          </button>
          <button
            onClick={rawMode ? saveRaw : saveStructured}
            className="flex items-center gap-1.5 rounded-xl bg-emerald-600 px-4 py-2 text-xs font-semibold text-white hover:bg-emerald-500"
          >
            <Save className="h-4 w-4" /> 保存配置
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-6">
        {rawMode ? (
          <textarea
            value={envYaml}
            onChange={(e) => setEnvYaml(e.target.value)}
            className="h-full min-h-[480px] w-full rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4 font-mono text-xs outline-none focus:border-sky-500"
          />
        ) : (
          <div className="grid max-w-5xl gap-5 md:grid-cols-2 text-xs">
            <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-5 space-y-3">
              <h2 className="text-sm font-bold">报告输出与台账路径</h2>
              <div>
                <label className="mb-1 block font-semibold">CNVD Word 报告输出目录</label>
                <input
                  value={paths.windows_report_output_dir || ''}
                  onChange={(e) => patchPath({ windows_report_output_dir: e.target.value })}
                  className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 font-mono"
                />
              </div>
              <div>
                <label className="mb-1 block font-semibold">SQLite 台账路径</label>
                <input
                  value={paths.tracker_db_path || ''}
                  onChange={(e) => patchPath({ tracker_db_path: e.target.value })}
                  className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 font-mono"
                />
              </div>
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={Boolean(paths.excel_sync?.enabled)}
                  onChange={(e) =>
                    patchPath({ excel_sync: { ...(paths.excel_sync || {}), enabled: e.target.checked } })
                  }
                />
                <span>生成报告时自动备份并追加到汇总 Excel</span>
              </label>
              {paths.excel_sync?.enabled && (
                <input
                  value={paths.excel_sync?.excel_path || ''}
                  onChange={(e) =>
                    patchPath({ excel_sync: { ...(paths.excel_sync || {}), excel_path: e.target.value } })
                  }
                  placeholder="C:/Users/.../漏挖/漏洞汇总.xlsx"
                  className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 font-mono"
                />
              )}
            </div>

            <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-5 space-y-3">
              <h2 className="text-sm font-bold">远程执行沙箱（SSH Ubuntu & WSL2）</h2>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="mb-1 block font-semibold">SSH Host 别名</label>
                  <input
                    value={ssh.host || ''}
                    onChange={(e) => patchSsh({ host: e.target.value })}
                    className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 font-mono"
                  />
                </div>
                <div>
                  <label className="mb-1 block font-semibold">WSL2 发行版</label>
                  <input
                    value={wsl.distro || ''}
                    onChange={(e) => patchWsl({ distro: e.target.value })}
                    className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 font-mono"
                  />
                </div>
              </div>
              <div>
                <label className="mb-1 block font-semibold">Ubuntu 工作区绝对路径</label>
                <input
                  value={ssh.workspace_root || ''}
                  onChange={(e) => patchSsh({ workspace_root: e.target.value })}
                  className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 font-mono"
                />
              </div>
            </div>

            <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-5 space-y-3 md:col-span-2">
              <h2 className="text-sm font-bold">Docker 代理、熔断与真 Burp 导流</h2>
              <div className="grid gap-3 md:grid-cols-3">
                <div>
                  <label className="mb-1 block font-semibold">HTTP_PROXY（拉镜像代理）</label>
                  <input
                    value={docker.http_proxy || ''}
                    onChange={(e) => patchDocker({ http_proxy: e.target.value, https_proxy: e.target.value })}
                    placeholder="http://127.0.0.1:7890"
                    className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 font-mono"
                  />
                </div>
                <div>
                  <label className="mb-1 block font-semibold">Burp 上游代理（可选真 BP 导流）</label>
                  <input
                    value={docker.burp_upstream_proxy || ''}
                    onChange={(e) => patchDocker({ burp_upstream_proxy: e.target.value || null })}
                    placeholder="http://192.168.159.1:8080"
                    className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 font-mono"
                  />
                </div>
                <div>
                  <label className="mb-1 block font-semibold">部署失败最大重试次数（熔断）</label>
                  <input
                    type="number"
                    min={0}
                    max={10}
                    value={docker.max_retries ?? 2}
                    onChange={(e) => patchDocker({ max_retries: Number(e.target.value) })}
                    className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2"
                  />
                </div>
              </div>
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={!docker.enforce_port_range}
                  onChange={(e) => patchDocker({ enforce_port_range: !e.target.checked })}
                />
                <span>允许隔离私网段上的常规应用端口（如 80 / 8035 / 8080 / 8088）</span>
              </label>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
