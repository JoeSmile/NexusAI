import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'

export type StatusKind = 'success' | 'warning' | 'error' | 'pending' | 'idle'

const LABEL: Record<StatusKind, string> = {
  success: '成功',
  warning: '警告',
  error: '错误',
  pending: '进行中',
  idle: '空闲',
}

const CLASS: Record<StatusKind, string> = {
  success: 'bg-[color-mix(in_srgb,var(--success)_12%,white)] text-[var(--success)]',
  warning: 'bg-[color-mix(in_srgb,var(--warning)_14%,white)] text-[var(--warning)]',
  error: 'bg-destructive/10 text-destructive',
  pending: 'bg-[color-mix(in_srgb,var(--primary)_12%,white)] text-primary',
  idle: 'bg-secondary text-muted-foreground',
}

export function StatusBadge({
  status,
  label,
  className,
}: {
  status: StatusKind
  label?: string
  className?: string
}) {
  return (
    <Badge
      className={cn('rounded-full gap-1', CLASS[status], className)}
      aria-label={label || LABEL[status]}
    >
      <span
        className="size-1.5 rounded-full bg-current"
        aria-hidden
      />
      {label || LABEL[status]}
    </Badge>
  )
}
