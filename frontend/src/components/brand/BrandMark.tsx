import { cn } from '@/lib/utils'

/** 文字品牌 + CSS 云蓝简标（Wave S：不引入 logo 图片） */
export function BrandMark({
  className,
  size = 'md',
}: {
  className?: string
  size?: 'sm' | 'md' | 'lg'
}) {
  const mark =
    size === 'lg' ? 'size-10 text-lg' : size === 'sm' ? 'size-6 text-xs' : 'size-8 text-sm'
  const word = size === 'lg' ? 'text-2xl' : size === 'sm' ? 'text-sm' : 'text-base'

  return (
    <div className={cn('flex items-center gap-2', className)}>
      <span
        aria-hidden
        className={cn(
          'inline-flex items-center justify-center rounded-md bg-primary font-semibold text-primary-foreground',
          mark,
        )}
      >
        N
      </span>
      <span className={cn('font-semibold tracking-tight text-foreground', word)}>
        NexusAI
      </span>
    </div>
  )
}
