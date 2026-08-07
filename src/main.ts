import { createApp } from 'vue'
import { createPinia } from 'pinia'
import './style.css'
import Root from './Root.vue'
import { router } from './router'

createApp(Root).use(createPinia()).use(router).mount('#app')
