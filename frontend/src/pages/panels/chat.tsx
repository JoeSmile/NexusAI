import { RequestPanel } from '@/components/panels/RequestPanel'
import { SSEPanel } from '@/components/panels/SSEPanel'

/** Chat 面板骨架：展示 RequestPanel + SSEPanel 三态（30.15）。 */
export default function ChatPanel() {
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Chat</h1>
        <p className="text-muted-foreground text-xs">
          通用面板组件预览（流式真实对接见 30.16）
        </p>
      </div>
      <SSEPanel demoText="打字机预览 · abort 可中断 · 心跳指示在真流式时闪烁。" />
      <RequestPanel
        title="短路径 JSON 探测"
        description="示例：GET /health（空态 / 成功 / 错误看状态徽章）"
        endpoint="/health"
        method="GET"
        fields={[]}
      />
    </div>
  )
}
