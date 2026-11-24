import { Cpu, Sparkles, Terminal } from 'lucide-react'

interface AgentIconProps {
  agent: string | null | undefined
  dark?: boolean
  size?: number
  className?: string
}

const SVG_MAP: Record<string, { light: string; dark: string; invertDark?: boolean }> = {
  codex: { light: '/agents/codex-light.svg', dark: '/agents/codex-dark.svg' },
  'claude-code': { light: '/agents/claude-light.svg', dark: '/agents/claude-dark.svg' },
  claude: { light: '/agents/claude-light.svg', dark: '/agents/claude-dark.svg' },
  dsh: { light: '/agents/deepseek-harness-light.svg', dark: '/agents/deepseek-harness-dark.svg' },
  'deepseek-harness': { light: '/agents/deepseek-harness-light.svg', dark: '/agents/deepseek-harness-dark.svg' },
  deepseek: { light: '/agents/deepseek-harness-light.svg', dark: '/agents/deepseek-harness-dark.svg' },
  'antigravity-cli': { light: '/agents/antigravity.svg', dark: '/agents/antigravity.svg', invertDark: true },
  antigravity: { light: '/agents/antigravity.svg', dark: '/agents/antigravity.svg', invertDark: true },
  'gemini-cli': { light: '/agents/gemini-light.svg', dark: '/agents/gemini-dark.svg' },
  gemini: { light: '/agents/gemini-light.svg', dark: '/agents/gemini-dark.svg' },
  opencode: { light: '/agents/opencode-light.svg', dark: '/agents/opencode-dark.svg' },
  cursor: { light: '/agents/cursor-light.svg', dark: '/agents/cursor-dark.svg' },
  cline: { light: '/agents/cline.svg', dark: '/agents/cline.svg' },
  kimi: { light: '/agents/kimi.svg', dark: '/agents/kimi.svg' },
}

export function AgentIcon({ agent, dark, size = 18, className = '' }: AgentIconProps) {
  const isDark =
    dark !== undefined
      ? dark
      : typeof document !== 'undefined' && document.documentElement.classList.contains('dark')
  const key = (agent || '').trim().toLowerCase()
  const entry = SVG_MAP[key]

  if (entry) {
    const src = isDark ? entry.dark : entry.light
    return (
      <img
        src={src}
        alt={key}
        width={size}
        height={size}
        className={`shrink-0 object-contain select-none ${isDark && entry.invertDark ? 'invert' : ''} ${className}`}
        style={{ width: size, height: size }}
        draggable={false}
      />
    )
  }

  if (key === 'openai-api' || key === 'openai') {
    return (
      <span
        className={`inline-flex shrink-0 items-center justify-center rounded-md bg-[var(--control-bg)] text-[var(--fg)] ${className}`}
        style={{ width: size, height: size }}
      >
        <Cpu style={{ width: size * 0.68, height: size * 0.68 }} />
      </span>
    )
  }

  if (key === 'native-subagent' || key === 'coordinator') {
    return (
      <span
        className={`inline-flex shrink-0 items-center justify-center rounded-md ${
          key === 'coordinator'
            ? 'bg-[var(--primary)] text-[var(--primary-fg)]'
            : 'bg-[var(--control-bg)] text-[var(--fg)]'
        } ${className}`}
        style={{ width: size, height: size }}
      >
        <Sparkles style={{ width: size * 0.62, height: size * 0.62 }} />
      </span>
    )
  }

  return (
    <span
      className={`inline-flex shrink-0 items-center justify-center rounded-md bg-[var(--control-bg)] text-[var(--muted)] ${className}`}
      style={{ width: size, height: size }}
    >
      <Terminal style={{ width: size * 0.65, height: size * 0.65 }} />
    </span>
  )
}
