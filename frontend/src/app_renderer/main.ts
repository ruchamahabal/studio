import { createApp } from "vue"
import { createPinia } from "pinia"
import app_router from "@/router/app_router"
import "@/setupFrappeUIResource"
import App from "@/App.vue"

import { resourcesPlugin } from "frappe-ui"
import { registerGlobalComponents } from "@/globals"

const app = createApp(App)
const pinia = createPinia()

// For the app renderer
app.use(app_router)
app.use(resourcesPlugin)
app.use(pinia)
registerGlobalComponents(app)
app.mount("#app")
