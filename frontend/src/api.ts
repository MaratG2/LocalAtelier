export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch("/api" + path, {
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
    throw new Error(payload.error || `Request failed (${response.status})`);
  return payload;
}
export const post = <T>(path: string, data: unknown = {}) =>
  api<T>(path, { method: "POST", body: JSON.stringify(data) });
export const patch = <T>(path: string, data: unknown) =>
  api<T>(path, { method: "PATCH", body: JSON.stringify(data) });
export const bytes = (value: number) =>
  value >= 1e9
    ? `${(value / 1e9).toFixed(1)} GB`
    : `${Math.round(value / 1e6)} MB`;
export const date = (value: number) =>
  new Date(value * 1000).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
