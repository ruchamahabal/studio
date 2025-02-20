import "../src/index.css"

import { createApp } from "vue"
import { createPinia } from "pinia"
import "../src/setupFrappeUIResource"
import app_router from "../src/router/app_router"
import App from "../src/App.vue"

import { registerGlobalComponents } from "../src/globals"

const pinia = createPinia()

// For rendering apps built by studio
const app = createApp(App)
app.use(app_router)
app.use(pinia)
registerGlobalComponents(app)
app.mount("#app")
