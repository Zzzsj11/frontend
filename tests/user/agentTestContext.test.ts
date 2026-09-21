import { afterEach, expect, it, vi } from 'vitest'
import { apiRequest } from '../../src/api/client'
import { agentTestHeaders } from '../../src/api/agentTestContext'

afterEach(() => {
  sessionStorage.clear()
  window.history.replaceState({}, '', '/')
  vi.restoreAllMocks()
})

it('keeps ordinary requests unmarked and confines explicit attribution to this tab', () => {
  expect(agentTestHeaders()).toEqual({})
  window.history.replaceState({}, '', '/projects?agent_test_run_id=dev01-test-123')
  expect(agentTestHeaders()).toEqual({
    'X-Agent-Name': 'code-agent',
    'X-Agent-Run-Id': 'dev01-test-123',
    'X-Test-Run-Id': 'dev01-test-123',
  })
  window.history.replaceState({}, '', '/projects')
  expect(agentTestHeaders()['X-Agent-Run-Id']).toBe('dev01-test-123')
  window.history.replaceState({}, '', '/projects?agent_test_run_id=off')
  expect(agentTestHeaders()).toEqual({})
})

it('does not mark malformed batch identifiers', () => {
  window.history.replaceState({}, '', '/projects?agent_test_run_id=bad%0Aid')
  expect(agentTestHeaders()).toEqual({})
})

it('sends all attribution headers and never replays a generation POST after a gateway error', async () => {
  window.history.replaceState({}, '', '/projects?agent_test_run_id=dev01-test-123')
  const fetchMock = vi
    .spyOn(globalThis, 'fetch')
    .mockResolvedValue(new Response('Bad Gateway', { status: 502 }))
  await expect(apiRequest('/generations/videos', { method: 'POST' })).rejects.toThrow()
  expect(fetchMock).toHaveBeenCalledTimes(1)
  const headers = fetchMock.mock.calls[0]?.[1]?.headers as Headers
  expect(headers.get('X-Agent-Name')).toBe('code-agent')
  expect(headers.get('X-Agent-Run-Id')).toBe('dev01-test-123')
  expect(headers.get('X-Test-Run-Id')).toBe('dev01-test-123')
})
