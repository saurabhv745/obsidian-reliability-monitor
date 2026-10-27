const cache = new Map();

/** Fetch JSON with a small in-memory TTL cache for read-only monitoring data. */
export async function cachedJson(url, options = {}, ttlMs = 30000) {
  const key = `${options.method || 'GET'}:${url}`;
  const hit = cache.get(key);
  if ((!options.method || options.method === 'GET') && hit && Date.now() - hit.time < ttlMs) return hit.value;
  const response = await fetch(url, options);
  if (!response.ok) throw new Error(`Request failed (${response.status})`);
  const value = await response.json();
  if (!options.method || options.method === 'GET') cache.set(key, { time: Date.now(), value });
  return value;
}

export function clearApiCache() { cache.clear(); }
