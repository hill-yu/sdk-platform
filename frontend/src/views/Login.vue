<template>
  <main class="login-page">
    <section class="login-card" aria-labelledby="login-title">
      <div class="login-mark" aria-hidden="true">✦</div>
      <p class="eyebrow">SDK PLATFORM</p>
      <h1 id="login-title">SDK 运营中台</h1>
      <p class="login-subtitle">登录后台，管理数据、配置与版本</p>
      <form @submit.prevent="submit">
        <label for="username">账号</label>
        <input id="username" v-model="username" autocomplete="username" maxlength="64" required autofocus />
        <label for="password">密码</label>
        <div class="password-field">
          <input id="password" v-model="password" :type="showPassword ? 'text' : 'password'" autocomplete="current-password" maxlength="256" required />
          <button type="button" class="toggle" :aria-label="showPassword ? '隐藏密码' : '显示密码'" @click="showPassword = !showPassword">{{ showPassword ? "隐藏" : "显示" }}</button>
        </div>
        <p v-if="errorMessage" class="error-message" role="alert">{{ errorMessage }}</p>
        <button class="submit-button" type="submit" :disabled="loading">{{ loading ? "正在登录…" : "登录" }}</button>
      </form>
    </section>
  </main>
</template>

<script setup lang="ts">
import { ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { login } from "@/api/auth";

const router = useRouter();
const route = useRoute();
const username = ref("");
const password = ref("");
const showPassword = ref(false);
const loading = ref(false);
const errorMessage = ref("");

function safeReturnTo(value: unknown) {
  const candidate = typeof value === "string" ? value : "/";
  return candidate.startsWith("/") && !candidate.startsWith("//") ? candidate : "/";
}

async function submit() {
  errorMessage.value = "";
  loading.value = true;
  try {
    await login(username.value, password.value);
    await router.replace(safeReturnTo(route.query.returnTo));
  } catch (error: any) {
    if (error?.response?.status === 503) errorMessage.value = "后台登录尚未配置，请联系管理员";
    else if (error?.response?.status === 429) errorMessage.value = "尝试次数过多，请稍后再试";
    else if (error?.response?.status === 401) errorMessage.value = "账号或密码错误";
    else if (error?.response) errorMessage.value = "登录失败，请检查账号或密码";
    else errorMessage.value = "网络连接失败，请检查后台服务";
  } finally {
    loading.value = false;
  }
}
</script>

<style scoped>
.login-page { min-height: 100dvh; display: grid; place-items: center; padding: 24px; background: linear-gradient(135deg, #f5f9ff, #eef4ff 52%, #ffffff); }
.login-card { width: min(100%, 410px); padding: 42px 40px; border: 1px solid #dbe7f8; border-radius: 20px; background: rgba(255,255,255,.94); box-shadow: 0 22px 60px rgba(37,99,235,.12); }
.login-mark { width: 48px; height: 48px; display: grid; place-items: center; border-radius: 14px; color: white; background: linear-gradient(135deg, #2563eb, #60a5fa); font-size: 26px; }
.eyebrow { margin: 24px 0 8px; color: #2563eb; font-size: 12px; letter-spacing: .25em; font-weight: 700; }
h1 { margin: 0; color: #172554; font-size: 28px; letter-spacing: -.04em; }
.login-subtitle { margin: 10px 0 28px; color: #64748b; }
label { display: block; margin: 16px 0 8px; color: #334155; font-size: 14px; font-weight: 600; }
input { width: 100%; min-height: 44px; padding: 0 13px; border: 1px solid #cbd5e1; border-radius: 10px; color: #1e293b; background: #fff; }
input:focus { border-color: #2563eb; box-shadow: 0 0 0 3px rgba(37,99,235,.14); outline: none; }
.password-field { position: relative; }
.password-field input { padding-right: 64px; }
.toggle { position: absolute; right: 8px; top: 6px; min-height: 32px; padding: 0 8px; border: 0; border-radius: 7px; color: #2563eb; background: transparent; font-size: 12px; }
.error-message { margin: 14px 0 0; color: #b91c1c; font-size: 13px; }
.submit-button { width: 100%; min-height: 46px; margin-top: 24px; border: 0; border-radius: 10px; color: #fff; background: #2563eb; font-weight: 700; }
.submit-button:hover:not(:disabled) { background: #1d4ed8; }
.submit-button:disabled { cursor: wait; opacity: .65; }
@media (max-width: 480px) { .login-page { padding: 16px; } .login-card { padding: 32px 24px; } }
</style>
