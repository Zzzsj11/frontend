import { computed, ref, watch } from 'vue'
import { alphabetical, modelVendor } from '../utils/modelCatalog'
import { modelDocs } from '../utils/modelDocs'
import { usePortal } from '../stores/portal'
export function useApiDocs() {
  const store = usePortal()
  const search = ref('')
  const selected = ref('')
  const category = ref('text')
  const exampleId = ref('generate')
  const categories = [
    { id: 'text', label: '文本' },
    { id: 'image', label: '图像' },
    { id: 'video', label: '视频' },
  ]
  const models = computed(() =>
    store.models.filter(
      (m) =>
        (category.value === 'text'
          ? ['chat', 'text'].includes(m.kind)
          : m.kind === category.value) &&
        `${m.id} ${modelVendor(m.id)}`.toLowerCase().includes(search.value.trim().toLowerCase()),
    ),
  )
  const groups = computed(() =>
    [...new Set(models.value.map((m) => modelVendor(m.id)))].sort(alphabetical).map((vendor) => ({
      vendor,
      models: models.value
        .filter((m) => modelVendor(m.id) === vendor)
        .sort((a, b) => alphabetical(a.id, b.id)),
    })),
  )
  watch(
    models,
    (items) => {
      if (!items.some((m) => m.id === selected.value)) selected.value = items[0]?.id || ''
    },
    { immediate: true },
  )
  watch(selected, () => (exampleId.value = 'generate'))
  const model = computed(() => models.value.find((m) => m.id === selected.value))
  const docs = computed(() => (model.value ? modelDocs(model.value) : null))
  const example = computed(
    () => docs.value?.examples.find((e) => e.id === exampleId.value) || docs.value?.examples[0],
  )
  const parameters = computed(() => {
    const m = model.value
    if (!m) return []
    const common = [
      { name: 'model', value: m.id },
      { name: 'Authorization', value: 'Bearer $MODEL_API_KEY' },
      { name: 'Idempotency-Key', value: '生成请求唯一标识；估价、查询不需要' },
    ]
    if (m.kind === 'chat')
      return [
        ...common,
        {
          name: docs.value?.path === '/v1/responses' ? 'input' : 'messages',
          value: '文本输入，结构见调用示例',
        },
        {
          name: docs.value?.path === '/v1/responses' ? 'max_output_tokens' : 'max_tokens',
          value: '示例为 128，按模型支持范围调整',
        },
      ]
    return [
      ...common,
      { name: 'prompt', value: '生成提示词，最多 20,000 字符' },
      ...(m.kind === 'image'
        ? [
            { name: 'size', value: '示例 1024x1024，按模型规格调整' },
            { name: 'n', value: '1–4，仍需符合所选模型限制' },
            { name: 'images', value: '可选参考图 URL 数组' },
          ]
        : [
            {
              name: 'duration',
              value: Array.isArray(m.capabilities.duration)
                ? m.capabilities.duration.join('–') + ' 秒'
                : '1–15 秒，具体支持范围以模型为准',
            },
            {
              name: 'resolution',
              value: Array.isArray(m.capabilities.resolution)
                ? m.capabilities.resolution.join(' / ')
                : '480p / 720p / 1080p，按模型能力选择',
            },
            {
              name: 'reference_mode',
              value: 'text / reference / first_frame / first_last / auto，按模型支持范围选择',
            },
            {
              name: 'images / videos / audios',
              value: '参考素材 URL 数组；统一接口最多 15 图、1 视频、3 音频，模型限制可能更低',
            },
          ]),
    ]
  })
  const fullGuide = computed(() =>
    model.value && docs.value
      ? [
          `# ${model.value.id}`,
          `状态：${model.value.enabled ? '已开放' : '暂未开放'}`,
          '请向管理员获取 MODEL_API_BASE（不含 /v1），并在服务端设置 MODEL_API_KEY。',
          ...(docs.value.custom
            ? ['此模型使用专用工作流接口，请联系管理员获取接入参数。']
            : parameters.value.map((p) => `${p.name}: ${p.value}`)),
          ...docs.value.examples.map((e) => `## ${e.label}\n${e.hint}\n${e.code}`),
          ...(docs.value.custom ? [] : [`成功响应（结构示意）：\n${docs.value.success}`]),
          `失败响应（结构示意）：\n${docs.value.failure}`,
          '费率配置：\n' + JSON.stringify(model.value.pricing, null, 2),
          '失败任务如产生实际费用仍会计费，用量缺失时待核账。',
        ].join('\n\n')
      : '',
  )

  return {
    search,
    selected,
    category,
    exampleId,
    categories,
    models,
    groups,
    model,
    docs,
    example,
    parameters,
    fullGuide,
    modelVendor,
  }
}
