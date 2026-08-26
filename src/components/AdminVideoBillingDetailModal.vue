<script setup lang="ts">
import type { VideoBillingDetail } from '../api/adminVideoBilling'
import BaseModal from './base/BaseModal.vue'

withDefaults(
  defineProps<{ open: boolean; loading?: boolean; detail?: VideoBillingDetail | null }>(),
  { loading: false, detail: null },
)
const emit = defineEmits<{ close: [] }>()

const isImage = (type: string, url: string) =>
  type.includes('图片') || type === 'image' || /\.(png|jpe?g|webp|gif)(\?|$)/i.test(url)
const money = (value: number) => `¥${value.toFixed(6)}`
</script>

<template>
  <BaseModal
    :open="open"
    :loading="loading"
    title="视频费用与生成详情"
    width="1000px"
    @close="emit('close')"
  >
    <div class="detail-body">
      <p v-if="loading">加载中…</p>
      <template v-else-if="detail">
        <section class="facts">
          <div>
            <span>工单</span><b>{{ detail.generationJobId }}</b>
          </div>
          <div>
            <span>生成来源</span>
            <b :class="{ agent: detail.generationOrigin === 'agent_test' }">
              {{ detail.generationOrigin === 'agent_test' ? 'Agent 开发测试' : '正常业务' }}
              <template v-if="detail.agentRunId">
                · {{ detail.agentName }} / {{ detail.agentRunId }}
              </template>
            </b>
          </div>
          <div>
            <span>供应商任务</span><b>{{ detail.providerTaskId || '-' }}</b>
          </div>
          <div>
            <span>模型 / 渠道</span><b>{{ detail.model }} / {{ detail.provider }}</b>
          </div>
          <div>
            <span>请求 / 供应商规格</span
            ><b>{{ detail.resolution }} / {{ detail.providerResolution || '-' }}</b>
          </div>
          <div>
            <span>实际媒体规格</span
            ><b>
              <template v-if="detail.actualWidth && detail.actualHeight">
                {{ detail.actualWidth }}×{{ detail.actualHeight }} · {{ detail.fps || '-' }} FPS ·
                {{ detail.codec || '-' }}
              </template>
              <template v-else>历史任务未采集</template>
            </b>
          </div>
          <div>
            <span>请求 / 实际时长</span
            ><b>{{ detail.durationSeconds || '-' }} 秒 / {{ detail.actualDuration || '-' }} 秒</b>
          </div>
          <div>
            <span>计价标准</span><b>{{ detail.rateLabel }}</b>
          </div>
          <div v-if="detail.discountLabel">
            <span>供应商折扣</span><b class="discount">{{ detail.discountLabel }}</b>
          </div>
          <div>
            <span>计费用量</span><b>{{ detail.usageQuantity }} {{ detail.usageUnit }}</b>
          </div>
          <div>
            <span>本次费用</span><b class="amount">{{ money(detail.amount) }}</b>
          </div>
          <div>
            <span>生成状态</span
            ><b :class="{ failed: detail.status !== 'succeeded' }">{{ detail.status }}</b>
          </div>
        </section>

        <section v-if="detail.error" class="error-box">
          <h3>失败原因</h3>
          <p>{{ detail.error }}</p>
        </section>

        <section>
          <h3>输出提示词</h3>
          <div v-for="prompt in detail.prompts" :key="prompt.label" class="prompt-block">
            <h4>{{ prompt.label }}</h4>
            <pre>{{ prompt.content }}</pre>
          </div>
          <p v-if="!detail.prompts.length" class="empty">该历史任务没有保存提示词</p>
        </section>

        <section>
          <h3>参考素材</h3>
          <div class="references">
            <article v-for="reference in detail.references" :key="reference.label + reference.url">
              <a :href="reference.url" target="_blank" rel="noopener noreferrer">
                <img
                  v-if="isImage(reference.type, reference.url)"
                  :src="reference.url"
                  :alt="reference.label"
                />
                <span v-else class="media-link">打开{{ reference.type }}</span>
              </a>
              <b>{{ reference.label }}</b>
              <small>{{ reference.type }}</small>
              <small v-if="reference.providerUrl" class="provider-reference">
                供应商引用：{{ reference.providerUrl }}
              </small>
            </article>
          </div>
          <p v-if="!detail.references.length" class="empty">本次生成没有参考素材</p>
        </section>

        <section v-if="detail.result.videoUrl">
          <h3>输出视频</h3>
          <video :src="detail.result.videoUrl" controls preload="metadata" />
        </section>

        <section>
          <h3>供应商原始用量</h3>
          <pre class="raw">{{ JSON.stringify(detail.rawUsage, null, 2) }}</pre>
        </section>
      </template>
    </div>
  </BaseModal>
</template>

<style scoped>
.detail-body {
  display: flex;
  flex-direction: column;
  gap: 20px;
  max-height: 75vh;
  overflow: auto;
  padding: 20px;
}
.facts {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}
.facts div {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 10px;
  background: var(--surface-muted);
  border-radius: var(--radius-sm);
}
.facts span,
small,
.empty {
  color: var(--text-secondary);
  font-size: var(--font-sm);
}
.facts b {
  overflow-wrap: anywhere;
}
.amount {
  color: var(--primary);
}
.agent {
  color: var(--primary);
}
.discount {
  color: var(--warning);
}
.failed {
  color: var(--danger);
}
h3,
h4,
p {
  margin: 0;
}
section {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.error-box {
  padding: 12px;
  background: var(--danger-light);
  color: var(--danger);
  border-radius: var(--radius-sm);
}
.prompt-block {
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  overflow: hidden;
}
.prompt-block h4 {
  padding: 8px 10px;
  background: var(--surface-muted);
}
pre {
  margin: 0;
  padding: 12px;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  font-size: var(--font-sm);
  line-height: 1.6;
}
.references {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}
.references article {
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.references a {
  display: flex;
  align-items: center;
  justify-content: center;
  aspect-ratio: 1;
  background: var(--surface-muted);
  border-radius: var(--radius-sm);
  overflow: hidden;
}
.references img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.media-link {
  color: var(--primary);
}
.provider-reference {
  overflow-wrap: anywhere;
}
video {
  width: 100%;
  max-height: 480px;
  background: var(--text);
  border-radius: var(--radius-sm);
}
.raw {
  background: var(--surface-muted);
  border-radius: var(--radius-sm);
}
@media (max-width: 700px) {
  .facts {
    grid-template-columns: 1fr;
  }
  .references {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
