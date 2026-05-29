import { createApp } from "vue";
import Antd from "ant-design-vue";
import "ant-design-vue/dist/reset.css";
import { createPinia } from "pinia";
import router from "./router";
import App from "./App.vue";

createApp(App).use(Antd).use(createPinia()).use(router).mount("#app");
