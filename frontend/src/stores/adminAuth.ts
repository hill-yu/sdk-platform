import { reactive } from "vue";

export interface AdminSession {
  username: string;
  expires_at: number;
  csrf_token: string;
}

export const adminAuth = reactive<{
  session: AdminSession | null;
  initialized: boolean;
  loading: boolean;
}>({ session: null, initialized: false, loading: false });

export const getCsrfToken = () => adminAuth.session?.csrf_token || "";

export function setAdminSession(session: AdminSession) {
  adminAuth.session = session;
  adminAuth.initialized = true;
}

export function clearAdminSession() {
  adminAuth.session = null;
  adminAuth.initialized = true;
}
