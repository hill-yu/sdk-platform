<template>
  <aside v-if="open" class="failure-drawer" data-testid="failure-drawer" aria-label="失败明细">
    <div class="drawer-header">
      <h4>失败分类</h4>
      <button data-testid="close-failure-drawer" class="ghost" type="button" @click="$emit('close')">关闭</button>
    </div>
    <p v-if="loading" class="muted">加载中…</p>
    <p v-else-if="!items.length" class="empty-state">暂无失败明细。</p>
    <div v-else class="table-scroll failure-scroll">
      <table class="table">
        <thead><tr><th>分类</th><th>次数</th><th>占比</th></tr></thead>
        <tbody>
          <tr v-for="item in items" :key="item.failure_category">
            <td>{{ item.failure_category }}</td>
            <td>{{ item.failure_count }}</td>
            <td :data-testid="`failure-share-${item.failure_category}`">{{ formatShare(item.share) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <p v-if="error" class="error">{{ error }}</p>
  </aside>
</template>

<script setup lang="ts">
import type { FailureBreakdownItem } from "@/api/logMetrics";

defineProps<{ open: boolean; items: FailureBreakdownItem[]; loading?: boolean; error?: string }>();
defineEmits<{ close: [] }>();

function formatShare(value: number | null) {
  return value === null ? "-" : `${Math.round(value * 100)}%`;
}
</script>

<style scoped>
.failure-drawer { display: grid; gap: 12px; padding: 16px; border: 1px solid var(--border-soft); border-radius: 10px; background: var(--surface-raised, rgba(18, 25, 24, .96)); }
.drawer-header { display: flex; align-items: center; justify-content: space-between; }
.drawer-header h4 { margin: 0; }
.table-scroll { overflow: auto; }
.failure-scroll { max-height: 240px; }
.ghost { border: 1px solid var(--border-soft); border-radius: 8px; background: transparent; color: var(--text-primary); padding: 6px 10px; cursor: pointer; }
.muted, .empty-state { color: var(--text-secondary); }
.error { color: var(--danger, #d9785d); }
</style>
