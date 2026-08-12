import { useLocation } from 'react-router-dom'

import { BrandMark } from '@/components/brand/BrandMark'

const META: Record<string, { title: string; wave: string; blurb: string }> = {
  '/workflows': {
    title: '工作流',
    wave: 'Wave C/D',
    blurb: '流程定义、发布与运行将在此上线。',
  },
  '/approvals': {
    title: '审批',
    wave: 'Wave E',
    blurb: '挂起待办与审批inbox将在此上线。',
  },
  '/governance/org': {
    title: '组织',
    wave: 'Wave B',
    blurb: '部门树、成员与业务角色将在此上线。',
  },
}

/** 产品化空态占位 — 不塞样例数据（Wave S） */
export default function PlaceholderPanel() {
  const { pathname } = useLocation()
  const meta = META[pathname] ?? {
    title: pathname.split('/').filter(Boolean).pop() || '模块',
    wave: '后续 Wave',
    blurb: '该模块尚在建设中。',
  }

  return (
    <div className="flex min-h-[50vh] flex-col items-center justify-center gap-4 px-4 text-center">
      <BrandMark size="lg" className="justify-center opacity-90" />
      <div className="space-y-2">
        <h1 className="text-xl font-semibold text-foreground">{meta.title}</h1>
        <p className="text-muted-foreground max-w-md text-sm">{meta.blurb}</p>
        <p className="text-muted-foreground text-xs">
          该模块将在 <span className="text-primary font-medium">{meta.wave}</span> 上线
        </p>
      </div>
    </div>
  )
}
