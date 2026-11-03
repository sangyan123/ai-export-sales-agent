import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import 'element-plus/dist/index.css'

import App from './App.vue'
import { permissionDirective } from './directives/permission'
import { router } from './router'
import { useAuthStore } from './stores/auth'
import './styles/index.css'

async function start(): Promise<void> {
  const app = createApp(App)
  const pinia = createPinia()

  app.use(pinia)
  await useAuthStore(pinia).bootstrap()

  app.use(router)
  app.use(ElementPlus, { locale: zhCn })
  app.directive('permission', permissionDirective)
  app.mount('#app')
}

void start()
