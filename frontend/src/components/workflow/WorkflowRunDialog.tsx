import { useEffect, useState } from 'react'

import {
  workflowRunInputs,
  type Workflow,
  type WorkflowParamSpec,
} from '@/api/workflows'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

function inputLabel(key: string, spec: WorkflowParamSpec) {
  return spec.description || spec.name || key
}

function defaultInputValues(specs: Record<string, WorkflowParamSpec>) {
  const values: Record<string, string> = {}
  for (const [key, spec] of Object.entries(specs)) {
    if (spec.default != null && spec.default !== '') values[key] = String(spec.default)
    else values[key] = ''
  }
  return values
}

export function collectWorkflowRunInput(
  specs: Record<string, WorkflowParamSpec>,
  values: Record<string, string>,
): { input: Record<string, unknown>; error?: string } {
  const input: Record<string, unknown> = {}
  for (const [key, spec] of Object.entries(specs)) {
    const raw = (values[key] ?? '').trim()
    if (raw) input[key] = raw
    else if (spec.default != null && spec.default !== '') input[key] = spec.default
    else if (spec.required) {
      return { input, error: `请填写「${inputLabel(key, spec)}」` }
    }
  }
  return { input }
}

export function WorkflowRunDialog({
  workflow,
  busy = false,
  onClose,
  onSubmit,
  onError,
}: {
  workflow: Workflow | null
  busy?: boolean
  onClose: () => void
  onSubmit: (input: Record<string, unknown>) => void | Promise<void>
  onError?: (message: string) => void
}) {
  const specs = workflowRunInputs(workflow?.ir)
  const [values, setValues] = useState<Record<string, string>>({})

  useEffect(() => {
    setValues(defaultInputValues(workflowRunInputs(workflow?.ir)))
  }, [workflow])

  async function confirm() {
    const { input, error } = collectWorkflowRunInput(specs, values)
    if (error) {
      onError?.(error)
      return
    }
    await onSubmit(input)
  }

  return (
    <Dialog open={workflow != null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>运行「{workflow?.name}」</DialogTitle>
          <DialogDescription>按流程声明的输入填写参数后启动。</DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          {Object.entries(specs).map(([key, spec]) => (
            <div key={key} className="space-y-1">
              <Label htmlFor={`wf-input-${key}`}>
                {inputLabel(key, spec)}
                {spec.required ? ' *' : ''}
              </Label>
              <Input
                id={`wf-input-${key}`}
                value={values[key] ?? ''}
                onChange={(e) => setValues((prev) => ({ ...prev, [key]: e.target.value }))}
              />
            </div>
          ))}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            取消
          </Button>
          <Button disabled={busy} onClick={() => void confirm()}>
            开始运行
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
