import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import type { SensitiveFinding } from '@/lib/clientGuardrails'

type Props = {
  open: boolean
  findings: SensitiveFinding[]
  onOpenChange: (open: boolean) => void
  onConfirm: () => void
}

export function SensitiveSendConfirmDialog({
  open,
  findings,
  onOpenChange,
  onConfirm,
}: Props) {
  const labels = findings.map((f) => f.label).join('、')
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md" overlayClassName="bg-[rgba(15,23,42,0.65)]">
        <DialogHeader>
          <DialogTitle>确认发送到服务器？</DialogTitle>
        </DialogHeader>
        <p className="text-sm text-[#334155]">
          检测到疑似敏感内容（{labels}）。消息将原样发送到服务器处理，请确认是否继续。
        </p>
        <p className="text-xs text-[#64748B]">
          前端仅作体验提示，不会替代后端护栏与审计。
        </p>
        <DialogFooter className="gap-2 sm:gap-2">
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            返回编辑
          </Button>
          <Button type="button" onClick={onConfirm}>
            仍要发送
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
