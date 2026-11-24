import React from 'react'
import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'
import { X } from 'lucide-react'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/* ── Button (Tahoe compact 32px default / 28px sm) ─────────────────── */
type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger'

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  size?: 'sm' | 'md'
}

export function Button({
  variant = 'secondary',
  size = 'md',
  className,
  ...props
}: ButtonProps) {
  return (
    <button
      {...props}
      className={cn(
        'inline-flex items-center justify-center gap-1.5 font-medium transition-colors duration-150 select-none disabled:pointer-events-none disabled:opacity-45 cursor-pointer',
        size === 'sm' ? 'h-7 rounded-lg px-2.5 text-xs' : 'h-8 rounded-[10px] px-3 text-[13px]',
        variant === 'primary' &&
          'bg-[var(--primary)] text-[var(--primary-fg)] shadow-[var(--shadow-xs)] hover:bg-[var(--primary-hover)]',
        variant === 'secondary' &&
          'border border-[var(--border)] bg-[var(--surface)] text-[var(--fg)] hover:bg-[var(--surface-hover)]',
        variant === 'ghost' &&
          'bg-transparent text-[var(--muted)] hover:bg-[var(--control-bg)] hover:text-[var(--fg)]',
        variant === 'danger' &&
          'border border-[var(--danger-border)] bg-[var(--danger-bg)] text-[var(--danger)] hover:brightness-95',
        className,
      )}
    />
  )
}

/* ── Segmented Control (macOS / Dimo native pill switcher) ─────────── */
export function SegmentedControl<T extends string>({
  value,
  onChange,
  options,
  className,
}: {
  value: T
  onChange: (val: T) => void
  options: { value: T; label: React.ReactNode; icon?: React.ReactNode }[]
  className?: string
}) {
  return (
    <div
      className={cn(
        'inline-flex items-center rounded-[10px] bg-[var(--control-bg)] p-0.5 border border-[var(--border)]',
        className,
      )}
    >
      {options.map((opt) => {
        const active = opt.value === value
        return (
          <button
            key={opt.value}
            type="button"
            onClick={() => onChange(opt.value)}
            className={cn(
              'inline-flex h-7 items-center gap-1.5 rounded-[8px] px-2.5 text-xs font-medium transition-all duration-150 cursor-pointer',
              active
                ? 'bg-[var(--surface)] text-[var(--fg)] shadow-[var(--shadow-xs)]'
                : 'text-[var(--muted)] hover:text-[var(--fg)]',
            )}
          >
            {opt.icon}
            {opt.label}
          </button>
        )
      })}
    </div>
  )
}

/* ── Switch (Tahoe ink pill toggle) ────────────────────────────────── */
export function Switch({
  checked,
  onChange,
  disabled,
}: {
  checked: boolean
  onChange: (checked: boolean) => void
  disabled?: boolean
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cn(
        'relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors duration-150 cursor-pointer disabled:opacity-40',
        checked ? 'bg-[var(--primary)]' : 'bg-[var(--border-strong)]',
      )}
    >
      <span
        className={cn(
          'inline-block h-3.5 w-3.5 rounded-full transition-transform duration-150',
          checked
            ? 'translate-x-[18px] bg-[var(--primary-fg)]'
            : 'translate-x-[3px] bg-[var(--surface)]',
        )}
      />
    </button>
  )
}

/* ── Status Pill (restrained semantic dot + label) ─────────────────── */
type Tone = 'neutral' | 'ok' | 'warn' | 'danger' | 'info'

export function StatusPill({
  tone = 'neutral',
  children,
  dot,
  className,
}: {
  tone?: Tone
  children: React.ReactNode
  dot?: boolean
  className?: string
}) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-medium leading-4 whitespace-nowrap',
        tone === 'neutral' && 'border-[var(--border)] bg-[var(--control-bg)] text-[var(--muted)]',
        tone === 'ok' && 'border-[var(--ok-border)] bg-[var(--ok-bg)] text-[var(--ok)]',
        tone === 'warn' && 'border-[var(--warn-border)] bg-[var(--warn-bg)] text-[var(--warn)]',
        tone === 'danger' && 'border-[var(--danger-border)] bg-[var(--danger-bg)] text-[var(--danger)]',
        tone === 'info' && 'border-[var(--info-border)] bg-[var(--info-bg)] text-[var(--info)]',
        className,
      )}
    >
      {dot && (
        <span
          className={cn(
            'h-1.5 w-1.5 rounded-full',
            tone === 'neutral' && 'bg-[var(--muted)]',
            tone === 'ok' && 'bg-[var(--ok)]',
            tone === 'warn' && 'bg-[var(--warn)]',
            tone === 'danger' && 'bg-[var(--danger)]',
            tone === 'info' && 'bg-[var(--info)]',
          )}
        />
      )}
      {children}
    </span>
  )
}

/* ── Form Inputs (32px height, 10px radius, hairline border) ───────── */
export function Input({ className, ...props }: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className={cn(
        'h-8 w-full rounded-[10px] border border-[var(--border)] bg-[var(--surface)] px-2.5 text-[13px] text-[var(--fg)] placeholder:text-[var(--subtle)] transition-colors hover:border-[var(--border-strong)]',
        className,
      )}
    />
  )
}

export function Select({ className, ...props }: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      {...props}
      className={cn(
        'h-8 w-full rounded-[10px] border border-[var(--border)] bg-[var(--surface)] px-2.5 text-[13px] text-[var(--fg)] transition-colors hover:border-[var(--border-strong)] cursor-pointer',
        className,
      )}
    />
  )
}

export function Field({
  label,
  hint,
  children,
}: {
  label: string
  hint?: string
  children: React.ReactNode
}) {
  return (
    <label className="block space-y-1">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-medium text-[var(--fg-secondary)]">{label}</span>
        {hint && <span className="text-[11px] text-[var(--muted)]">{hint}</span>}
      </div>
      {children}
    </label>
  )
}

/* ── Modal Dialog (Opaque Tahoe dialog surface) ────────────────────── */
export function Modal({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  maxWidth = 'max-w-lg',
}: {
  open: boolean
  onClose: () => void
  title: string
  description?: string
  children: React.ReactNode
  footer?: React.ReactNode
  maxWidth?: string
}) {
  if (!open) return null
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-4 backdrop-blur-[2px]"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div className={cn('tahoe-popover w-full overflow-hidden', maxWidth)}>
        <div className="flex items-start justify-between gap-3 border-b border-[var(--border)] px-5 py-4">
          <div>
            <h3 className="text-sm font-semibold text-[var(--fg)]">{title}</h3>
            {description && <p className="mt-0.5 text-xs text-[var(--muted)]">{description}</p>}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="flex h-7 w-7 items-center justify-center rounded-lg text-[var(--muted)] hover:bg-[var(--control-bg)] hover:text-[var(--fg)] cursor-pointer"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="max-h-[70vh] overflow-y-auto px-5 py-4">{children}</div>
        {footer && (
          <div className="flex items-center justify-end gap-2 border-t border-[var(--border)] bg-[var(--surface-subtle)] px-5 py-3">
            {footer}
          </div>
        )}
      </div>
    </div>
  )
}
