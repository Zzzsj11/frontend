import { createApp } from 'vue'
import { createPinia } from 'pinia'
import './style.css'
import Root from './Root.vue'
import { router } from './router'
import { startPerfMonitoring } from './perf'

// 会话级性能观测：主线程长任务监听（Long Task API），管理后台「性能」页可查
startPerfMonitoring()

createApp(Root).use(createPinia()).use(router).mount('#app')
