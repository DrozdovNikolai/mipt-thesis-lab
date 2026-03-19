import { baseUrl } from './config';
import type { Tokens } from './models';

export class ApiError extends Error {
  constructor(readonly status: number, message: string) { super(message); }
}

function errorMessage(body: string, status: number) {
  try {
    const { detail } = JSON.parse(body);
    if (typeof detail === 'string') return detail;
    if (typeof detail?.message === 'string') return detail.message;
    if (Array.isArray(detail)) return detail.map(issue => issue.msg).join('\n');
  } catch { /* Non-JSON responses use the HTTP status below. */ }
  return `Сервер вернул HTTP ${status}`;
}

async function request<T>(path: string, body?: unknown, accessToken?: string): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 20000);
  try {
    const response = await fetch(baseUrl + path, {
      method: body === undefined ? 'GET' : 'POST',
      signal: controller.signal,
      headers: {
        Accept: 'application/json',
        ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
        ...(accessToken ? { Authorization: 'Bearer ' + accessToken } : {}),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const text = await response.text();
    if (!response.ok) throw new ApiError(response.status, errorMessage(text, response.status));
    return text ? JSON.parse(text) : undefined;
  } finally { clearTimeout(timeout); }
}

