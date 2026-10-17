import { createRouter, createWebHistory } from "vue-router";

import Dashboard from "@/views/Dashboard.vue";
import ConfigManager from "@/views/ConfigManager.vue";
import LogViewer from "@/views/LogViewer.vue";
import VersionManager from "@/views/VersionManager.vue";
import Login from "@/views/Login.vue";
import { me } from "@/api/auth";
import { adminAuth } from "@/stores/adminAuth";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/login", name: "login", component: Login, meta: { public: true } },
    { path: "/", name: "dashboard", component: Dashboard },
    { path: "/logs", name: "logs", component: LogViewer },
    { path: "/config", name: "config", component: ConfigManager },
    { path: "/version", name: "version", component: VersionManager },
  ],
});

router.beforeEach(async (to) => {
  if (to.meta.public) return true;
  if (!adminAuth.initialized) {
    try {
      await me();
    } catch {
      adminAuth.initialized = true;
    }
  }
  if (adminAuth.session) return true;
  const returnTo = `${to.fullPath}`;
  return { name: "login", query: { returnTo: returnTo.startsWith("/") && !returnTo.startsWith("//") ? returnTo : "/" } };
});

export default router;
