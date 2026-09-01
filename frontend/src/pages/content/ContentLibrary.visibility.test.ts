import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

describe('ContentLibrary visibility (45b.4)', () => {
  it('exposes share confirm and private/shared markers', () => {
    const src = readFileSync(
      join(process.cwd(), 'src/pages/content/ContentLibrary.tsx'),
      'utf8',
    )
    expect(src).toMatch(/共享给本租户/)
    expect(src).toMatch(/确认共享/)
    expect(src).toMatch(/setArtifactVisibility/)
    expect(src).toMatch(/已共享/)
  })
})
