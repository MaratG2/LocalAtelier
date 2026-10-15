import { t, locale } from "./i18n";
let workspace: string | undefined;
let resetting = false;
export function setWorkspace(value?: string) {
  workspace = value;
}
export async function studioFetch(
  path: string,
  init?: RequestInit,
): Promise<Response> {
  const headers = new Headers(init?.headers);
  if (workspace) headers.set("X-Atelier-Space", workspace);
  const response = await fetch(path, { ...init, headers, cache: "no-store" });
  if (
    (response.status === 423 || response.status === 409) &&
    !path.startsWith("/api/personal")
  ) {
    const payload = await response
      .clone()
      .json()
      .catch(() => ({}));
    if (
      ["space_locked", "space_changed"].includes(payload.code) &&
      !resetting
    ) {
      resetting = true;
      window.dispatchEvent(new Event("atelier-space-locked"));
      await fetch("/api/personal/lock", { method: "POST" });
      location.replace("/settings?locked=1");
    }
  }
  return response;
}
export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await studioFetch("/api" + path, {
    ...init,
    headers:
      init?.body instanceof FormData
        ? init.headers
        : { "Content-Type": "application/json", ...init?.headers },
  });
  let payload;
  try {
    payload = await response.json();
  } catch {
    throw new Error(
      "The studio returned an unreadable response. Check the local server.",
    );
  }
  if (!response.ok)
    throw new Error(t(payload.error || `Request failed (${response.status})`));
  return payload;
}
export const post = <T>(path: string, data: unknown = {}) =>
  api<T>(path, { method: "POST", body: JSON.stringify(data) });
export const patch = <T>(path: string, data: unknown) =>
  api<T>(path, { method: "PATCH", body: JSON.stringify(data) });
export const bytes = (value: number) =>
  value >= 1e9
    ? `${(value / 1e9).toLocaleString(locale(), { maximumFractionDigits: 1 })} ${t("GB")}`
    : `${Math.round(value / 1e6).toLocaleString(locale())} ${t("MB")}`;
export const date = (value: number) =>
  new Date(value * 1000).toLocaleDateString(locale(), {
    month: "short",
    day: "numeric",
  });
