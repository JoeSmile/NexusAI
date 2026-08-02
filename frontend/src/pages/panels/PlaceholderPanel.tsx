import { useLocation } from 'react-router-dom'

/** 各面板占位，30.16+ 替换为真实页。 */
export default function PlaceholderPanel() {
  const { pathname } = useLocation()
  const name = pathname.split('/').pop() || 'panel'
  return (
    <div className="space-y-1">
      <h1 className="text-xl font-semibold capitalize">{name}</h1>
      <p className="text-muted-foreground text-xs">面板占位 — 后续子任务接入</p>
    </div>
  )
}
