<template>
  <div class="shell" :class="{ 'home-light': route.name === 'dashboard' }">
    <aside class="sidebar">
      <div class="brand">
        <span class="brand-kicker">SDK PLATFORM</span>
        <h1>运营中台</h1>
        <p>数据、配置、版本统一管理</p>
      </div>

      <nav class="nav">
        <RouterLink to="/" class="nav-link">数据大盘</RouterLink>
        <RouterLink to="/logs" class="nav-link">日志查看</RouterLink>
        <RouterLink to="/config" class="nav-link">配置管理</RouterLink>
        <RouterLink to="/version" class="nav-link">版本管理</RouterLink>
      </nav>
    </aside>

    <main class="content" :class="{ 'home-light-content': route.name === 'dashboard' }">
      <header class="topbar">
        <div>
          <p v-if="route.name === 'dashboard'" class="breadcrumb">运营中台&nbsp; / &nbsp;数据大盘</p>
          <template v-else><p class="eyebrow">Admin Console</p><h2>{{ routeTitle }}</h2></template>
        </div>
        <div v-if="route.name === 'dashboard'" class="home-meta">北京时间 UTC+8</div>
        <div v-else class="token-tip">
          当前使用本地 `admin_token`
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
import { RouterLink, RouterView, useRoute } from "vue-router";

const route = useRoute();

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
  grid-template-columns: 280px minmax(0, 1fr);
  overflow: hidden;
  background:
    radial-gradient(circle at top left, rgba(214, 140, 69, 0.28), transparent 28%),
    radial-gradient(circle at bottom right, rgba(75, 122, 91, 0.22), transparent 32%),
    var(--bg-primary);
}

.shell.home-light { grid-template-columns: 224px minmax(0, 1fr); background: #f5f7fa; }

.sidebar {
  min-width: 0;
  min-height: 0;
  overflow-y: auto;
  padding: 32px 24px;
  border-right: 1px solid var(--border-soft);
  background: linear-gradient(180deg, rgba(16, 27, 26, 0.95), rgba(24, 36, 34, 0.78));
  backdrop-filter: blur(14px);
}

.home-light .sidebar { padding: 20px 10px; border-right: 1px solid #e5e7eb; background: #fff; backdrop-filter: none; }
.home-light .brand { padding: 0 16px; }
.home-light .brand-kicker { display: none; }
.home-light .brand h1 { color: #1f2937; font-size: 20px; letter-spacing: -0.02em; }
.home-light .brand p { color: #64748b; font-size: 12px; }

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

.home-light .nav { margin-top: 26px; gap: 4px; }

.nav-link {
  color: var(--text-primary);
  text-decoration: none;
  border: 1px solid transparent;
  padding: 14px 16px;
  border-radius: 16px;
  transition: all 0.25s ease;
  background: rgba(255, 255, 255, 0.03);
}

.home-light .nav-link { color: #334155; border-radius: 6px; padding: 12px 16px; background: transparent; }
.home-light .nav-link:hover, .home-light .nav-link:focus-visible { color: #1d4ed8; background: #eff6ff; outline: 2px solid #93c5fd; outline-offset: 2px; }

.nav-link.router-link-active {
  background: linear-gradient(135deg, rgba(214, 140, 69, 0.22), rgba(86, 145, 114, 0.18));
  border-color: rgba(214, 140, 69, 0.35);
  box-shadow: 0 18px 32px rgba(0, 0, 0, 0.16);
}

.home-light .nav-link.router-link-active { color: #2563eb; background: #e8f1ff; border-color: transparent; box-shadow: none; }

.content {
  min-width: 0;
  min-height: 0;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  overflow: hidden;
  padding: 24px;
}

.home-light-content { padding: 0 22px 22px; background: #f5f7fa; }
.home-light-content .topbar { min-height: 48px; margin: 0 -22px 18px; padding: 0 22px; align-items: center; border-bottom: 1px solid #e5e7eb; background: #fff; }
.breadcrumb, .home-meta { margin: 0; color: #64748b; font-size: 14px; }

.topbar {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-end;
  margin-bottom: 20px;
}

.token-tip {
  color: var(--text-muted);
  font-size: 13px;
}

.page {
  min-width: 0;
  min-height: 0;
  overflow-x: hidden;
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

  .shell.home-light { grid-template-columns: minmax(0, 1fr); }
  .home-light .sidebar { padding: 12px 10px; }
  .home-light .brand { padding: 0 12px; }
  .home-light .nav { flex-direction: row; overflow-x: auto; margin-top: 12px; }
  .home-light .nav-link { flex: 0 0 auto; white-space: nowrap; }
}
</style>
