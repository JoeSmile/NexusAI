import { Suspense, lazy, useMemo } from 'react'

import { ALLOWED_COMPONENTS, COMPONENT_REGISTRY } from '@/components/dynamic/ComponentRegistry'
import type { RenderActionHandler, RenderDirective } from '@/types/render'

type Props = {
  directive: RenderDirective | null | undefined
  onAction?: RenderActionHandler
}

function UnknownComponent({ name }: { name: string }) {
  return (
    <p className="text-sm text-amber-700">
      未注册的组件：<code>{name}</code>（允许：{ALLOWED_COMPONENTS.join(', ')}）
    </p>
  )
}

export function RenderHost({ directive, onAction }: Props) {
  const componentName = directive?.component?.trim() || ''
  const payload = directive?.payload ?? {}

  const LazyComponent = useMemo(() => {
    if (!componentName || !ALLOWED_COMPONENTS.includes(componentName)) return null
    const loader = COMPONENT_REGISTRY[componentName]
    if (!loader) return null
    return lazy(loader)
  }, [componentName])

  if (!directive || !componentName) return null
  if (!LazyComponent) return <UnknownComponent name={componentName} />

  return (
    <div className="render-host mt-3 rounded-xl border border-[#E2E8F0] bg-[#F8FAFC] p-3">
      <Suspense fallback={<p className="text-sm text-muted-foreground">加载组件…</p>}>
        <LazyComponent payload={payload} onAction={onAction} />
      </Suspense>
    </div>
  )
}
