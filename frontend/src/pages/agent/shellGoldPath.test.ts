import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const here = dirname(fileURLToPath(import.meta.url))

describe('Task 47 shell gold path', () => {
  it('HomeChat keeps hotspot and script shortcuts', () => {
    const src = readFileSync(join(here, 'HomeChat.tsx'), 'utf8')
    expect(src).toContain("label: '抓取热点'")
    expect(src).toContain("label: '生成口播稿'")
  })

  it('ContentStudio keeps org profile and style management', () => {
    const src = readFileSync(
      join(here, '..', 'content', 'ContentStudio.tsx'),
      'utf8',
    )
    expect(src).toContain('机构画像')
    expect(src).toContain('主讲风格')
    expect(src).toContain('生成口播稿')
  })
})
