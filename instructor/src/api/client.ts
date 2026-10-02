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
    return JSON.parse(text || 'null') as T;
  } finally { clearTimeout(timeout); }
}

function tokenPair(value: Tokens) {
  if (!value?.accessToken || !value.refreshToken) throw new Error('Сервер не выдал пару токенов');
  return value;
}

export class Client {
  private refreshing?: Promise<void>;
  private constructor(private tokens: Tokens) {}

  static async login(login: string, password: string) {
    const tokens = await request<Tokens>('/auth/login', { login: login.trim(), password });
    return new Client(tokenPair(tokens));
  }

private refresh() {
    this.refreshing ??= request<Tokens>('/auth/refresh', { refreshToken: this.tokens.refreshToken })
      .then(tokens => { this.tokens = tokenPair(tokens); })
      .finally(() => { this.refreshing = undefined; });
    return this.refreshing;
  }

async send<T>(path: string, body?: unknown): Promise<T> {
    const token = this.tokens.accessToken;
    try { return await request<T>(path, body, token); }
    catch (error) {
      if (!(error instanceof ApiError) || error.status !== 401) throw error;
      if (this.tokens.accessToken === token) await this.refresh();
      return request<T>(path, body, this.tokens.accessToken);
    }
  }

async logout() {
    await request('/auth/logout-refresh', { refreshToken: this.tokens.refreshToken });
  }
}

