# 前端组件开发规范

适用范围：`src/`、`tests/`、`e2e/` 内的所有前端代码。新代码必须遵循本规范；修改存量代码时遵循"顺手整改"原则，触及的区域按规范对齐。

工程卡口：`make lint-frontend` = `npm run format:check`（Prettier）+ `npm run lint`（ESLint）。格式问题只允许通过 `npm run format` 修复，禁止手工调整格式。

## 1. 技术栈与文件组织

技术栈基线：Vue 3 SFC + `<script setup lang="ts">` + Pinia（选项式 store）+ Vue Router + Vite。**禁止新增 Options API 组件**。

| 目录 | 职责 | 约束 |
|---|---|---|
| `src/views/` | 路由级页面 | 只组合组件与读取 store，不写业务逻辑 |
| `src/components/` | 业务组件 | 可访问 store |
| `src/components/base/` | 无业务基础组件（BaseModal 等） | 禁止访问 store，只通过 props/emits 通信 |
| `src/stores/` | Pinia 状态 | 跨组件状态才入 store |
| `src/api/` | 所有 HTTP 调用 | 组件内禁止直接 fetch/axios |
| `src/composables/` | 可复用组合式函数 | 命名 `useXxx.ts` |
| `src/types/` | 跨模块 TypeScript 类型 | 集中定义，组件/store 复用 |

单文件行数上限：组件 ≤ 300 行，超出须拆分子组件或 composable；store ≤ 500 行，超出按领域拆分。

## 2. 命名规范

- 文件与组件：PascalCase（`MagicScriptModal.vue`）；composable：`useConfirmDialog.ts`；store：`useProjectStore`
- CSS 类：kebab-case；状态修饰沿用现有风格：`active` / `selected` / `disabled` / `loading`
- props：camelCase；布尔 props 以 `is/has/can/disabled` 开头
- emits：kebab-case 或动词原形（`close`、`update:modelValue`）

```vue
<!-- ✅ 正例 -->
<script setup lang="ts">
withDefaults(defineProps<{ src?: string; label?: string }>(), { label: '' })
const emit = defineEmits<{ close: [] }>()
</script>

<!-- ❌ 反例：运行时声明、无默认值、any -->
<script setup>
const props = defineProps(['src', 'label'])
</script>
```

## 3. 组件编写规范

SFC 块顺序固定（ESLint `vue/block-order` 强制）：`<script setup>` → `<template>` → `<style scoped>`。

`<script setup>` 内部顺序（ESLint `vue/define-macros-order` 强制宏顺序）：

1. import
2. props / emits 声明
3. store / router / composable
4. 响应式状态（ref / reactive）
5. computed
6. watch
7. 方法
8. 生命周期钩子

其他约定：

- props/emits 一律使用 TS 类型声明，可选 props 用 `withDefaults` 提供默认值
- 禁止裸 `any`（ESLint warn，整改完成后升 error）；`types/index.ts` 已有的类型优先复用
- 模板中禁止多语句内联事件（`@click="a = 1; b = 2"`），抽为具名方法；这也能避免 Prettier 换行破坏语句分隔
- 注释使用中文，说明"为什么"而非复述代码，密度与现有代码一致

## 4. 样式与设计令牌

一律 `<style scoped>`；全局样式只允许出现在 `src/style.css`（令牌 + 通用工具类）。

**组件内禁止硬编码色值、圆角、阴影、z-index**，一律使用设计令牌（定义见 `src/style.css` `:root`）：

| 类别 | 令牌 |
|---|---|
| 色彩 | `--primary` `--primary-hover` `--primary-gradient` `--success` `--warning` `--danger` 及各自 `-light` 底色；`--text` `--text-secondary` `--bg` `--border` `--border-dark` |
| 圆角 | `--radius-sm`(8) `--radius-md`(12) `--radius-lg`(16) `--radius-pill`(20) |
| 阴影 | `--shadow-card` `--shadow-dropdown` `--shadow-modal` |
| 字号 | `--font-sm`(12) `--font-md`(14) `--font-lg`(17) |

```css
/* ✅ 正例 */
.close-btn:hover {
  color: var(--primary);
  border-radius: var(--radius-sm);
}

/* ❌ 反例：硬编码近似色与魔法数字 */
.close-btn:hover {
  color: #e65b2d;
  border-radius: 9px;
}
```

### z-index 层级表（成文固定，新增弹层必须查表）

| 层级 | 用途 |
|---|---|
| 0~20 | 工作区内部元素（拖拽柄、时间轴刻度等） |
| 600 | 顶部菜单栏 AppHeader |
| 1000 | 一级弹框遮罩（BaseModal 默认档） |
| 1100 | 弹框内二级弹层（BaseModal `level="nested"`） |
| 1200 | 全局确认对话框 ConfirmDialog |
| 2000 | 全局错误对话框 ErrorDialog |

禁止自创层级值；确认框与错误框必须高于一切业务弹框。

## 5. 弹层（Modal）规范

所有遮罩弹层**必须使用 `src/components/base/BaseModal.vue`**，禁止手写遮罩。BaseModal 已封装：

- `<Teleport to="body">` + `position:fixed;inset:0` + z-index 档位
- 点击遮罩关闭（`@click.self`）+ Esc 关闭，`loading` 时禁止关闭
- `role="dialog"` `aria-modal="true"` `aria-label`
- 三段式结构：`.modal-header`（标题 + 关闭按钮）/ `.modal-body` / `.modal-footer`

```vue
<!-- ✅ 正例 -->
<BaseModal :open="store.magicOpen" title="ASS 视频" :loading="store.magicLoading" @close="cancel">
  <template #body>…</template>
  <template #footer>…</template>
</BaseModal>

<!-- ❌ 反例：手写 Teleport + mask + 关闭逻辑 -->
<Teleport to="body">
  <div v-if="open" class="my-mask" @click.self="close">…</div>
</Teleport>
```

全局单例反馈组件：`ConfirmDialog`（二次确认，经 `useConfirmDialog` 调用）、`ErrorDialog`（错误，经 `errorBus` 上报），业务代码不重复实现。

## 6. 状态与 API 规范

- Pinia 选项式 store；跨组件共享状态才入 store，局部状态留在组件内
- API 统一走 `src/api/client.ts` 封装，不在组件内拼请求
- 错误统一经 `errorBus` 上报 ErrorDialog 展示，组件不重复弹错误框
- 异步操作三态成对命名：`xxxLoading` / `xxxError` / `xxx`（数据本体），与 store 现有命名一致

## 7. 可访问性（a11y）基线

- 弹框：`role="dialog"` + `aria-modal="true"` + `aria-label`
- 仅图标按钮：必须有 `title` 或 `aria-label`
- 禁用状态用 `disabled` 属性，禁止只用样式模拟
- 表单控件关联 `<label>` 或 `aria-label`

## 8. 工程化卡口

| 工具 | 配置 | 强制点 |
|---|---|---|
| Prettier | `.prettierrc.json` | `make lint-frontend` 中 `format:check`，唯一格式来源 |
| ESLint | `eslint.config.js` | `vue/recommended` + `vue/block-order` + `vue/define-macros-order`；格式类规则已关闭（交 Prettier） |
| vue-tsc | `npm run build` | strict 类型检查 |
| vitest | `npm test` | 单测随 `make preflight` 执行 |

存量宽松项（`no-explicit-any` 等为 warn）在存量整改完成后收紧为 error，届时更新本章节。
