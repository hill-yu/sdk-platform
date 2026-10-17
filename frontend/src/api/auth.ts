import request from "./request";
import { clearAdminSession, setAdminSession, type AdminSession } from "@/stores/adminAuth";

export async function login(username: string, password: string) {
  const session = (await request.post("/auth/login", { username, password })) as AdminSession;
  setAdminSession(session);
  return session;
}

export async function me() {
  const session = (await request.get("/auth/me")) as AdminSession;
  setAdminSession(session);
  return session;
}

export async function logout() {
  try {
    await request.post("/auth/logout");
  } finally {
    clearAdminSession();
  }
}
