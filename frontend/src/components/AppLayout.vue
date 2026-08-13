<template>
  <div class="shell">
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

    <main class="content">
      <header class="topbar">
        <div>
          <p class="eyebrow">Admin Console</p>
          <h2>{{ routeTitle }}</h2>
        </div>
        <div class="token-tip">
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
  min-height: 100vh;
  display: grid;
  grid-template-columns: 280px 1fr;
  background:
    radial-gradient(circle at top left, rgba(214, 140, 69, 0.28), transparent 28%),
    radial-gradient(circle at bottom right, rgba(75, 122, 91, 0.22), transparent 32%),
    var(--bg-primary);
}

.sidebar {
  padding: 32px 24px;
  border-right: 1px solid var(--border-soft);
  background: linear-gradient(180deg, rgba(16, 27, 26, 0.95), rgba(24, 36, 34, 0.78));
  backdrop-filter: blur(14px);
}

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

.nav-link {
  color: var(--text-primary);
  text-decoration: none;
  border: 1px solid transparent;
  padding: 14px 16px;
  border-radius: 16px;
  transition: all 0.25s ease;
  background: rgba(255, 255, 255, 0.03);
}

.nav-link.router-link-active {
  background: linear-gradient(135deg, rgba(214, 140, 69, 0.22), rgba(86, 145, 114, 0.18));
  border-color: rgba(214, 140, 69, 0.35);
  box-shadow: 0 18px 32px rgba(0, 0, 0, 0.16);
}

.content {
  padding: 24px;
}

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
  min-height: calc(100vh - 120px);
}

@media (max-width: 920px) {
  .shell {
    grid-template-columns: 1fr;
  }

  .sidebar {
    border-right: none;
    border-bottom: 1px solid var(--border-soft);
  }

  .topbar {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
