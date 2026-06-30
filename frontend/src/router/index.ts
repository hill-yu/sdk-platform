import { createRouter, createWebHistory } from "vue-router";

import Dashboard from "@/views/Dashboard.vue";
import ConfigManager from "@/views/ConfigManager.vue";
import VersionManager from "@/views/VersionManager.vue";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", name: "dashboard", component: Dashboard },
    { path: "/config", name: "config", component: ConfigManager },
    { path: "/version", name: "version", component: VersionManager },
  ],
});

export default router;
