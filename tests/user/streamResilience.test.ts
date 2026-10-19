import { expect, it, vi } from 'vitest'
import { streamMaterialExport, streamStoryboardOutline } from '../../src/api/domain'

const response = (events: string[]) =>
  new Response(
    new ReadableStream({
      start(controller) {
        controller.enqueue(
          new TextEncoder().encode(events.map((event) => `data: ${event}\n\n`).join('')),
        )
        controller.close()
      },
    }),
    { headers: { 'Content-Type': 'text/event-stream' } },
  )

it('大纲流跳过畸形事件并继续接收有效进度', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    response([
      '{broken',
      '{"type":"outline"}',
      '{"type":"outline","taskId":"t1","status":"outlining","progress":{"phase":"generating"}}',
    ]),
  )
  const received = vi.fn()
  await streamStoryboardOutline('t1', received)
  expect(received).toHaveBeenCalledTimes(1)
  expect(received.mock.calls[0][0].taskId).toBe('t1')
})

it('导出流跳过空工单和畸形 JSON，保留后续终态', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    response([
      '{broken',
      '{"type":"export","export":null}',
      '{"type":"export","export":{"id":"e1","status":"ready"}}',
    ]),
  )
  const received = vi.fn()
  await streamMaterialExport('e1', received)
  expect(received).toHaveBeenCalledExactlyOnceWith({ id: 'e1', status: 'ready' })
})
