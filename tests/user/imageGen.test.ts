import { describe, expect, it } from 'vitest'
import { DEFAULT_IMAGE_WAIT_TIMEOUT_MS } from '../../src/api/imageGen'

describe('image generation timeout contract', () => {
  it('waits beyond the backend ten-minute provider deadline', () => {
    expect(DEFAULT_IMAGE_WAIT_TIMEOUT_MS).toBe(660_000)
  })
})
