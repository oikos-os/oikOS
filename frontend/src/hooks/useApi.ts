import { useEffect, useState } from "react";

export function useApi<T>(url: string, interval?: number) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    async function fetchData() {
      try {
        const res = await fetch(url);
        if (!res.ok) throw new Error(`${res.status}`);
        const json = await res.json();
        if (active) {
          setData(json);
          setError(null);
        }
      } catch (e) {
        if (active) setError(String(e));
      }
    }

    fetchData();

    if (interval) {
      const id = setInterval(fetchData, interval);
      return () => { active = false; clearInterval(id); };
    }

    return () => { active = false; };
  }, [url, interval]);

  return { data, error };
}
