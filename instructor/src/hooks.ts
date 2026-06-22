import { useCallback, useEffect, useRef, useState } from 'react';

function message(error: unknown) {
  if (error instanceof Error && error.name === 'AbortError') return 'Сервер не ответил вовремя. Повторите запрос.';
  return error instanceof Error ? error.message : 'Не удалось выполнить запрос';
}

