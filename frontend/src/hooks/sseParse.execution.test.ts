import { describe, expect, it } from 'vitest'

import { applyExecutionEvent, type ExecutionState } from '@/hooks/sseParse'

describe('applyExecutionEvent step status (Task 85 F2)', () => {
  it('ignores a late running event after succeeded and keeps summary updates', () => {
    let state: ExecutionState | null = null
    state = applyExecutionEvent(state, {
      type: 'step',
      id: 's1',
      capability_id: 'web.search',
      status: 'running',
    })
    state = applyExecutionEvent(state, {
      type: 'step',
      id: 's1',
      status: 'succeeded',
      summary: 'done',
    })
    state = applyExecutionEvent(state, {
      type: 'step',
      id: 's1',
      status: 'running',
      summary: 'late-note',
    })
    expect(state.steps[0].status).toBe('succeeded')
    expect(state.steps[0].summary).toBe('late-note')
    expect(state.activeTool).toBeNull()
  })

  it('is idempotent for repeated succeeded events', () => {
    let state: ExecutionState | null = applyExecutionEvent(null, {
      type: 'step',
      id: 's1',
      status: 'succeeded',
      summary: 'ok',
    })
    const again = applyExecutionEvent(state, {
      type: 'step',
      id: 's1',
      status: 'succeeded',
      summary: 'ok',
    })
    expect(again.steps[0].status).toBe('succeeded')
    expect(again.steps).toHaveLength(1)
  })

  it('allows pending → running → succeeded', () => {
    let state = applyExecutionEvent(null, {
      type: 'step',
      id: 's1',
      status: 'pending',
    })
    state = applyExecutionEvent(state, { type: 'step', id: 's1', status: 'running' })
    expect(state.steps[0].status).toBe('running')
    state = applyExecutionEvent(state, { type: 'step', id: 's1', status: 'succeeded' })
    expect(state.steps[0].status).toBe('succeeded')
  })

  it('drops synthetic planning step when a real plan arrives', () => {
    let state = applyExecutionEvent(null, {
      type: 'plan',
      goal: '正在理解你的需求…',
      steps: [{ id: '_planning', capability_id: 'task.plan', status: 'running' }],
    })
    state = applyExecutionEvent(state, {
      type: 'plan',
      goal: '写口播',
      steps: [{ id: 's1', capability_id: 'llm.generate' }],
    })
    expect(state.steps.map((s) => s.id)).toEqual(['s1'])
    expect(state.goal).toBe('写口播')
  })
})
