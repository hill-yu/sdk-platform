<template>
  <div class="shell light-shell">
    <aside class="sidebar">
      <div class="brand">
        <span class="brand-kicker">SDK PLATFORM</span>
        <div class="brand-title">
          <svg class="brand-mark" viewBox="0 0 32 32" aria-hidden="true"><path d="M16 2 28 9v14l-12 7L4 23V9l12-7Z" fill="#2563eb"/><path d="m16 2 12 7-12 7L4 9l12-7Z" fill="#60a5fa"/><path d="M16 16v14l12-7V9l-12 7Z" fill="#1d4ed8"/><path d="m16 10 4 2.3v4.6l-4 2.3-4-2.3v-4.6l4-2.3Z" fill="#fff" opacity=".94"/></svg>
          <h1>SDK 运营中台</h1>
        </div>
        <p>数据、配置、版本统一管理</p>
      </div>

      <nav class="nav">
        <RouterLink to="/" class="nav-link"><span class="nav-icon" aria-hidden="true">▥</span>数据大盘</RouterLink>
        <RouterLink to="/logs" class="nav-link"><span class="nav-icon" aria-hidden="true">▤</span>日志查看</RouterLink>
        <RouterLink to="/config" class="nav-link"><span class="nav-icon" aria-hidden="true">⚙</span>配置管理</RouterLink>
        <RouterLink to="/version" class="nav-link"><span class="nav-icon" aria-hidden="true">◇</span>版本管理</RouterLink>
      </nav>
    </aside>

    <main class="content light-content">
      <header class="topbar">
        <p class="breadcrumb">运营中台&nbsp; / &nbsp;{{ routeTitle }}</p>
        <div class="topbar-actions">
          <div class="home-meta">{{ adminAuth.session?.username || "admin" }} · 北京时间 UTC+8</div>
          <button class="logout-button" type="button" @click="handleLogout">退出</button>
        </div>
      </header>
      <section class="page">
        <RouterView />
      </section>
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { RouterLink, RouterView, useRoute, useRouter } from "vue-router";
import { logout } from "@/api/auth";
import { adminAuth } from "@/stores/adminAuth";

const route = useRoute();
const router = useRouter();

async function handleLogout() {
  try {
    await logout();
    await router.replace({ name: "login" });
  } catch {
    await router.replace({ name: "login", query: { logoutError: "1" } });
  }
}

const routeTitle = computed(() => {
  if (route.name === "logs") return "日志查看";
  if (route.name === "config") return "配置管理";
  if (route.name === "version") return "版本管理";
  return "数据大盘";
});
</script>

<style scoped>
.shell {
  width: 100%;
  height: 100dvh;
  min-width: 0;
  min-height: 0;
  display: grid;
  grid-template-columns: 224px minmax(0, 1fr);
  overflow: hidden;
  background: var(--bg-primary);
}

.light-shell { background: var(--bg-primary); }

.sidebar {
  min-width: 0;
  min-height: 0;
  overflow-y: auto;
  padding: 20px 10px;
  border-right: 1px solid var(--border-soft);
  background: var(--bg-secondary);
}

.brand { padding: 0 16px; }
.brand-kicker { display: none; }
.brand-title { display: flex; align-items: center; gap: 10px; }
.brand-mark { width: 26px; height: 26px; flex: 0 0 auto; }
.brand h1 { color: var(--text-primary); font-size: 20px; letter-spacing: -0.02em; white-space: nowrap; }
.brand p { color: var(--text-muted); font-size: 12px; }

.brand-kicker,
.eyebrow {
  font-size: 12px;
  letter-spacing: 0.28em;
  text-transform: uppercase;
  color: var(--text-muted);
}

.brand h1,
.topbar h2 {
  margin: 8px 0;
}

.brand p {
  color: var(--text-muted);
  line-height: 1.6;
}

.nav {
  margin-top: 32px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.nav { margin-top: 26px; gap: 4px; }

.nav-link {
  display: flex;
  align-items: center;
  gap: 12px;
  color: #334155;
  text-decoration: none;
  border: 1px solid transparent;
  padding: 12px 16px;
  border-radius: 6px;
  transition: all 0.25s ease;
  background: transparent;
}

.nav-icon { width: 20px; color: var(--text-muted); font-size: 20px; line-height: 1; text-align: center; }
.nav-link:hover, .nav-link:focus-visible { color: #1d4ed8; background: var(--hover-bg); outline: 2px solid var(--focus-ring); outline-offset: 2px; }
.nav-link:hover .nav-icon, .nav-link.router-link-active .nav-icon { color: var(--accent); }

.nav-link.router-link-active { color: var(--accent); background: #e8f1ff; border-color: transparent; box-shadow: none; }

.content {
  min-width: 0;
  min-height: 0;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  overflow: hidden;
  padding: 0 22px 22px;
}

.light-content { background: var(--bg-primary); }
.light-content .topbar { min-height: 48px; margin: 0 -22px 18px; padding: 0 22px; align-items: center; border-bottom: 1px solid var(--border-soft); background: var(--bg-secondary); }
.breadcrumb, .home-meta { margin: 0; color: var(--text-muted); font-size: 14px; }
.topbar-actions { display: flex; align-items: center; gap: 14px; }
.logout-button { border: 1px solid var(--border-soft); border-radius: 7px; padding: 7px 12px; color: var(--text-secondary); background: var(--bg-secondary); }
.logout-button:hover { color: var(--accent); border-color: var(--hover-border); background: var(--hover-bg); }

.topbar {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-end;
  margin-bottom: 20px;
}

.page {
  min-width: 0;
  min-height: 0;
  overflow-x: auto;
  overflow-y: auto;
  overscroll-behavior: contain;
}

@media (max-width: 920px) {
  .shell {
    grid-template-columns: minmax(0, 1fr);
    grid-template-rows: auto minmax(0, 1fr);
  }

  .sidebar {
    border-right: none;
    border-bottom: 1px solid var(--border-soft);
  }

  .topbar {
    flex-direction: column;
    align-items: flex-start;
  }

  .light-shell { grid-template-columns: minmax(0, 1fr); }
  .sidebar { padding: 12px 10px; }
  .brand { padding: 0 12px; }
  .nav { flex-direction: row; gap: 0; overflow-x: auto; margin-top: 12px; }
  .nav-link { flex: 0 0 auto; gap: 6px; padding: 10px 7px; font-size: 14px; white-space: nowrap; }
  .nav-icon { width: 16px; font-size: 17px; }
}
</style>
