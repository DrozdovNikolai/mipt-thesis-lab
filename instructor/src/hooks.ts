import { useCallback, useEffect, useRef, useState } from 'react';

function message(error: unknown) {
  if (error instanceof Error && error.name === 'AbortError') return 'Сервер не ответил вовремя. Повторите запрос.';
  return error instanceof Error ? error.message : 'Не удалось выполнить запрос';
}

function useMounted() {
  const live = useRef(false);
  useEffect(() => { live.current = true; return () => { live.current = false; }; }, []);
  return live;
}

export function useAction() {
  const mounted = useMounted();
  const lock = useRef(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function run(work: () => Promise<void>) {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    setError('');
    try { await work(); }
    catch (e) { if (mounted.current) setError(message(e)); }
    finally {
      lock.current = false;
      if (mounted.current) setBusy(false);
    }
  }
  return { busy, error, run };
}

export function useLoad<T>(load: () => Promise<T>) {
  const [revision, setRevision] = useState(0);
  const [state, setState] = useState<{ data?: T; error?: string }>({});
  useEffect(() => {
    let current = true;
    setState({});
    load().then(data => { if (current) setState({ data }); })
      .catch(e => { if (current) setState({ error: message(e) }); });
    return () => { current = false; };
  }, [load, revision]);
  const retry = useCallback(() => setRevision(n => n + 1), []);
  return { ...state, retry };
}

