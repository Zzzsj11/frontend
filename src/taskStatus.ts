/**
 * 任务状态中文标注（侧边栏任务列表徽章 / 编辑器横幅共用）。
 * ASS 两阶段流程新增 parsed（拆分完成待生成大纲）/ outlining（大纲生成中）/ outline_failed（大纲失败）。
 */
export const TASK_STATUS_LABELS: Record<string, string> = {
  parsed: '待生成大纲',
  outlining: '大纲生成中',
  outline_failed: '大纲失败',
  generating: '生成中',
  partial: '部分失败',
  failed: '生成失败',
}

/** 需要醒目提示（警示色）的失败态 */
export const TASK_STATUS_ALERTS = new Set(['outline_failed', 'partial', 'failed'])

export const taskStatusLabel = (status?: string): string =>
  status ? (TASK_STATUS_LABELS[status] ?? '') : ''

export const taskStatusAlert = (status?: string): boolean =>
  !!status && TASK_STATUS_ALERTS.has(status)
