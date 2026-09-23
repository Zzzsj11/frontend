import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { createRouter, createWebHistory } from 'vue-router'
import PortalView from './views/PortalView.vue'
import { RouterView } from 'vue-router'
import './style.css'
const router = createRouter({
  history: createWebHistory(),
  routes: [{ path: '/:pathMatch(.*)*', component: PortalView }],
})
createApp(RouterView).use(createPinia()).use(router).mount('#app')
