const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";
const API_TOKEN = import.meta.env.VITE_API_TOKEN ?? "";


function buildHeaders(initHeaders?: HeadersInit, expectJson?: boolean): Headers {
  const headers = new Headers(initHeaders);
  if (expectJson && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (API_TOKEN && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${API_TOKEN}`);
  }
  return headers;
}


export async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: buildHeaders(init?.headers),
  });
  if (!response.ok) {
    throw new Error(`请求失败，状态码 ${response.status}`);
  }
  return (await response.json()) as T;
}


export async function postJson<T>(path: string, body: unknown, init?: RequestInit): Promise<T> {
  return requestJson<T>(path, {
    ...init,
    method: init?.method ?? "POST",
    headers: buildHeaders(init?.headers, true),
    body: JSON.stringify(body),
  });
}


export function createFormHeaders(initHeaders?: HeadersInit): Headers {
  return buildHeaders(initHeaders);
}
