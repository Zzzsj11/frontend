import { createApp, h } from 'vue'
import { createPinia } from 'pinia'
import { createRouter, createWebHistory, RouterView } from 'vue-router'
import ConsoleView from './views/ConsoleView.vue'
import './style.css'
const router = createRouter({
  history: createWebHistory(),
  routes: [{ path: '/:pathMatch(.*)*', component: ConsoleView }],
})
createApp({ render: () => h(RouterView) })
  .use(createPinia())
  .use(router)
  .mount('#app')
