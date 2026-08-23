import type { ReactNode } from 'react'

type ConsoleSectionPageProps = {
  title: string
  description: string
  children?: ReactNode
}

export function ConsoleSectionPage({ title, description, children }: ConsoleSectionPageProps) {
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">{title}</h1>
        <p className="text-muted-foreground text-sm">{description}</p>
      </div>
      {children}
    </div>
  )
}
