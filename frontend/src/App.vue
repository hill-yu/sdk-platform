<template>
  <AppLayout v-if="route.name !== 'login'" />
  <RouterView v-else />
</template>

<script setup lang="ts">
import { RouterView, useRoute } from "vue-router";
import { onBeforeUnmount, onMounted } from "vue";
import AppLayout from "@/components/AppLayout.vue";
import router from "@/router";

const route = useRoute();

function redirectAfterExpiry() {
  if (router.currentRoute.value.name === "login") return;
  const returnTo = router.currentRoute.value.fullPath;
  void router.replace({ name: "login", query: { returnTo: returnTo.startsWith("/") && !returnTo.startsWith("//") ? returnTo : "/" } });
}

onMounted(() => window.addEventListener("admin-auth-expired", redirectAfterExpiry));
onBeforeUnmount(() => window.removeEventListener("admin-auth-expired", redirectAfterExpiry));
</script>
