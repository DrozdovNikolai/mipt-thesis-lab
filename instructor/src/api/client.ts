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

