/**
 * Shared right overlay drawer — covers chat, does not flex-squeeze.
 * Context config and Bookmarks each use this shell as separate features.
 */
import type { ReactNode } from 'react'

import { cn } from '@/lib/utils'

export function RightDrawer({
  open,
  title,
  onClose,
  children,
  className,
}: {
  open: boolean
  title: string
  onClose: () => void
  children: ReactNode
  className?: string
}) {
  if (!open) return null

  return (
    <div className="right-drawer-root" role="presentation">
      <button
        type="button"
        className="right-drawer-backdrop"
        aria-label="关闭面板"
        onClick={onClose}
      />
      <aside
        className={cn('right-drawer-panel', className)}
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <div className="right-drawer-header">
          <div className="right-drawer-title">{title}</div>
          <button
            type="button"
            className="right-drawer-close"
            onClick={onClose}
            title="关闭"
            aria-label="关闭"
          >
            ×
          </button>
        </div>
        <div className="right-drawer-body">{children}</div>
      </aside>
    </div>
  )
}
