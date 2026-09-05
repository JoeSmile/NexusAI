import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { capabilityLabel, ExecutionPanel } from '@/components/agent/ExecutionPanel'

describe('ExecutionPanel (Task 88 A3)', () => {
  it('maps capability ids to Chinese labels', () => {
    expect(capabilityLabel('rag.search')).toBe('检索公司知识库')
    expect(capabilityLabel('unknown.cap')).toBe('unknown.cap')
  })

  it('renders human-readable step names', () => {
    render(
      <ExecutionPanel
        execution={{
          goal: '写口播',
          steps: [
            {
              id: 's1',
              capability_id: 'llm.generate',
              status: 'running',
            },
          ],
        }}
      />,
    )
    expect(screen.getByText('生成文案')).toBeTruthy()
    expect(screen.queryByText('llm.generate')).toBeNull()
  })
})
