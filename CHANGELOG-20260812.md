# 2026-08-12 功能迭代汇总

## 后端改动

### 段重试改为后台任务（202 + 幂等）

- `POST /api/tasks/{id}/storyboard-outline/segments/{n}/regenerate` → 202 受理 + asyncio.create_task
- 重复提交返回 409
- SSE 端点适配 segment_retry / segment_retry_failed 进度推送
- GET /tasks/{id} 透传 outlineProgress 供前端轮询
- `_run_segment_retry()` 后台函数独立抽取

### LLM 错误日志系统

- `error_logging.py` 新增 `log_background_error()` 无需 Request 的错误记录
- `storyboard_prompt.py` 4 处埋点：`_call` HTTP异常、`_plan_ass_scenes` ValueError、`_generate_scene_shots` ValueError、`generate_storyboard_line` ValueError
- 所有 transient 错误（含被 retry/repair 恢复的）均写入 api_error_logs

### JSON 解析加固 & Prompt 强化

- `_extract_json()` 宽松解析：提取 `fence` → 从 {/[ 开始 → 逐字符跳过前缀 → 接受尾部文字
- 3 个 system prompt + user message 提醒：强调 "} 之后不要加任何文字"
- `buildPortraitPrompt` 超简提示词：仅描述"参照参考图替换人物"

### 数字人图片生成模板

- 系统人物 001 的三视图作为模板参考图（getTemplateAvatar/setTemplateAvatar）
- 所有生成/上传/重生流程自动传入模板图

### 并发限制 & 轮询间隔

- 图片/视频生成单用户并发上限 20，超限 429
- 轮询间隔 3s → 30s

### 排序 & 导出清理

- 数字人列表排序：用户角色(private)优先，系统角色在后
- 素材导出：每次新导出清理同任务历史记录
- `projects` 和 `project_tasks` 加 sort_order 字段，支持拖拽排序 API

### 其他

- 确认弹窗 Enter 键支持
- 视频/图片默认分辨率 480p
- ASS 任务标题改为"歌名 – 编号"
- 视频 API Key 从 AIGC_TOKEN 共享

## 前端改动

### 侧边栏

- 选中状态 localStorage 持久化，刷新恢复
- 最大宽度 1.69x（默认 232px，最大 392px）
- 拖拽排序（HTML5 drag & drop）
- 子项目标题 hover 全名提示
- 移除时间戳显示

### 数字人资产库

- 系统角色点击头像 → 全屏大图预览
- 编辑弹窗图片点击放大
- 合并"生成数字人"和"上传数字人"为统一入口
- 上传两阶段显示："正在上传…" → "正在生成三视图…"
- 生成期间表单 disabled 保持内容不变
- 卡片选中无压扁效果（scrollbar-gutter: stable + 去 transform 过渡）
- "角色被锁"提示：ASS 大纲已生成的行不支持修改角色

### 大纲弹窗

- Tab 切换："场景总览"（scenePlan + globalVisual）+ "逐镜大纲"（shots）

### 视频生成

- 下载按钮独立于导出按钮，完成后显示
- 视频分辨率默认 480p

### 通用分镜

- 默认参数：1 空镜 + 1 人物镜 + 8s 总时长

### 导出素材

- 导出和下载分成两个按钮
- 导出完成后下载按钮出现在旁边，导出按钮仍可继续使用

### 用户登录

- 401/403 自动刷新 token → 失败则跳转登录页

## 数据库迁移

- `c812a9e4d501_project_sort_order.py`
  - projects 加 sort_order INTEGER DEFAULT 0
  - project_tasks 加 sort_order INTEGER DEFAULT 0

## 自动化测试

- `test_storyboard_quality.py` 新增 2 个后端测试：段重试 202/409 幂等 + outlineProgress 查询
