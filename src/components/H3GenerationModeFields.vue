<script setup lang="ts">
import { computed } from 'vue'
import type { ShotGenOptions } from '../types'

const props = defineProps<{ modelValue: ShotGenOptions }>()
const emit = defineEmits<{ 'update:modelValue': [value: ShotGenOptions] }>()
const selectedMode = computed(() => props.modelValue.h3Mode ?? 'auto')
const update = <K extends keyof ShotGenOptions>(key: K, value: ShotGenOptions[K]) =>
  emit('update:modelValue', { ...props.modelValue, [key]: value })
const urls = (value: string, max: number) =>
  value
    .split(/[\n,]/)
    .map((item) => item.trim())
    .filter(Boolean)
    .slice(0, max)
</script>

<template>
  <fieldset class="mode-fields">
    <legend>H3 生成方式</legend>
    <label class="field"
      ><span>生成模式</span>
      <select
        :value="selectedMode"
        aria-label="H3 生成模式"
        @change="
          update('h3Mode', ($event.target as HTMLSelectElement).value as ShotGenOptions['h3Mode'])
        "
      >
        <option value="auto">自动推荐</option>
        <option value="text">纯文本 T2VA</option>
        <option value="first_frame">首帧 I2VA</option>
        <option value="first_last">首尾帧 FL2VA</option>
        <option value="reference">多参考 Ref2VA</option>
      </select>
    </label>
    <p class="hint">
      {{
        selectedMode === 'auto'
          ? '根据当前素材自动选择模式。'
          : selectedMode === 'text'
            ? '只提交提示词，不传入参考素材。'
            : selectedMode === 'first_frame'
              ? '首帧留空时使用当前场景图。'
              : selectedMode === 'first_last'
                ? '从首帧连续变化并准确落到尾帧。'
                : '综合人物、场景、动作和音频参考生成。'
      }}
    </p>
    <label v-if="selectedMode === 'first_frame' || selectedMode === 'first_last'" class="field"
      ><span>首帧图片 URL <small>留空使用当前场景图</small></span>
      <input
        :value="modelValue.h3FirstFrameUrl ?? ''"
        type="url"
        placeholder="https://…/first.jpg"
        @input="update('h3FirstFrameUrl', ($event.target as HTMLInputElement).value.trim())"
      />
    </label>
    <label v-if="selectedMode === 'first_last'" class="field"
      ><span>尾帧图片 URL <strong>必填</strong></span>
      <input
        :value="modelValue.h3LastFrameUrl ?? ''"
        type="url"
        placeholder="https://…/last.jpg"
        @input="update('h3LastFrameUrl', ($event.target as HTMLInputElement).value.trim())"
      />
    </label>
    <template v-if="selectedMode === 'reference'">
      <label class="field"
        ><span>补充参考图片 URL（最多6张）</span>
        <textarea
          :value="(modelValue.referenceImageUrls ?? []).join('\n')"
          rows="3"
          placeholder="当前场景图和人物图也计入6张上限"
          @input="
            update('referenceImageUrls', urls(($event.target as HTMLTextAreaElement).value, 6))
          "
        />
      </label>
      <label class="field"
        ><span>参考视频 URL（最多1段）</span>
        <textarea
          :value="(modelValue.referenceVideoUrls ?? []).join('\n')"
          rows="2"
          placeholder="2–15秒"
          @input="
            update('referenceVideoUrls', urls(($event.target as HTMLTextAreaElement).value, 1))
          "
        />
      </label>
      <label class="field"
        ><span>参考音频 URL（最多3段）</span>
        <textarea
          :value="(modelValue.referenceAudioUrls ?? []).join('\n')"
          rows="3"
          placeholder="每段2–15秒，总时长≤15秒，不能作为唯一输入"
          @input="
            update('referenceAudioUrls', urls(($event.target as HTMLTextAreaElement).value, 3))
          "
        />
      </label>
      <label class="field"
        ><span>音频用途</span>
        <select
          :value="modelValue.h3AudioUsage ?? 'reference'"
          @change="
            update(
              'h3AudioUsage',
              ($event.target as HTMLSelectElement).value as ShotGenOptions['h3AudioUsage'],
            )
          "
        >
          <option value="reference">参考节奏/风格</option>
          <option value="reuse">请求复用原音频</option>
          <option value="generated">由模型生成声音</option>
          <option value="mute">静音意图</option>
        </select>
      </label>
      <p class="hint">产品限制：最多6图、1视频、3音频，共最多10个文件。</p>
    </template>
  </fieldset>
</template>

<style scoped>
.mode-fields {
  display: grid;
  gap: 10px;
  min-width: 0;
  margin: 0 0 14px;
  padding: 12px 0 0;
  border: 0;
  border-top: 1px solid var(--border);
}
.mode-fields legend {
  padding: 0;
  color: var(--text-secondary);
  font-size: var(--font-sm);
}
.field {
  display: grid;
  gap: 5px;
  color: var(--text-regular);
  font-size: var(--font-sm);
}
.field small,
.hint {
  color: var(--text-secondary);
  font-size: 11px;
}
.field strong {
  color: var(--danger);
}
.field input,
.field textarea,
.field select {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface);
  color: var(--text);
  padding: 8px 10px;
  font: inherit;
}
.field textarea {
  resize: vertical;
}
.hint {
  margin: 0;
  line-height: 1.5;
}
</style>
