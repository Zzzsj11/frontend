import type { Model } from '../stores/portal'
export function modelDocs(model: Model) {
  const text = ['chat', 'text'].includes(model.kind)
  const native = String(model.capabilities.native_endpoint || '')
  const path =
    model.kind === 'chat'
      ? native === '/v1/responses'
        ? native
        : native === '/v1/messages' || model.id.startsWith('claude')
          ? '/v1/messages'
          : '/v1/chat/completions'
      : model.kind === 'image'
        ? '/v1/images'
        : '/v1/videos'
  const body =
    model.kind === 'chat'
      ? path === '/v1/responses'
        ? { model: model.id, input: '写一段简短的产品介绍', max_output_tokens: 128 }
        : {
            model: model.id,
            messages: [{ role: 'user', content: '写一段简短的产品介绍' }],
            max_tokens: 128,
          }
      : model.kind === 'image'
        ? {
            model: model.id,
            prompt: '清晨海边，一座白色灯塔，柔和自然光',
            size: '1024x1024',
            quality: 'auto',
          }
        : {
            model: model.id,
            prompt: '清晨海边，海浪轻拍礁石，镜头缓慢前移',
            duration: model.id.startsWith('veo') ? 8 : 5,
            resolution: '720p',
            reference_mode: 'text',
          }
  function curl(endpoint: string, payload?: unknown) {
    return `curl -X ${payload ? 'POST' : 'GET'} "$MODEL_API_BASE${endpoint}" \\\n  -H "Authorization: Bearer $MODEL_API_KEY"${payload ? ` \\\n  -H "Content-Type: application/json"${(payload as { estimate_only?: boolean }).estimate_only ? '' : ' \\\n  -H "Idempotency-Key: unique-request-id"'} \\\n  -d '${JSON.stringify(payload, null, 2).replaceAll("'", "'\"'\"'")}'` : ''}`
  }
  const examples = [
    {
      id: 'generate',
      label: text ? '文本调用' : '创建任务',
      path,
      code: curl(path, body),
      hint: text ? '文本接口按所选协议返回响应。' : '返回任务 ID 后，通过查询接口获取状态和结果。',
    },
    {
      id: 'estimate',
      label: '预估费用',
      path,
      code: curl(path, { ...body, estimate_only: true }),
      hint: '仅估价，不创建任务、不扣积分，无需 Idempotency-Key。',
    },
    ...(!text
      ? [
          {
            id: 'query',
            label: '查询任务',
            path: '/v1/jobs/{task_id}',
            code: curl('/v1/jobs/TASK_ID'),
            hint: '将 TASK_ID 替换为创建响应中的 id；请使用创建任务时的同一个 Key。',
          },
        ]
      : []),
  ]
  const success = text
    ? path === '/v1/messages'
      ? {
          id: 'MESSAGE_ID',
          type: 'message',
          content: [{ type: 'text', text: '产品介绍…' }],
          usage: { input_tokens: 12, output_tokens: 30 },
        }
      : path === '/v1/responses'
        ? {
            id: 'RESPONSE_ID',
            output: [{ type: 'message', content: [{ type: 'output_text', text: '产品介绍…' }] }],
          }
        : {
            id: 'COMPLETION_ID',
            choices: [{ message: { role: 'assistant', content: '产品介绍…' } }],
            usage: { prompt_tokens: 12, completion_tokens: 30 },
          }
    : {
        id: 'TASK_ID',
        model: model.id,
        kind: model.kind,
        status: 'queued',
        result: null,
        usage: null,
        error: null,
      }
  return {
    path,
    examples: model.kind === 'text' || model.id === 'minimax-h3-runninghub' ? [] : examples,
    success: JSON.stringify(success, null, 2),
    failure: JSON.stringify({ detail: '请求参数不符合模型要求' }, null, 2),
    custom: model.kind === 'text' || model.id === 'minimax-h3-runninghub',
  }
}
