import { imageUrl } from "./api";

export type ThumbnailSize = 160 | 320 | 960;

const CONCURRENCY = 4;
const MAX_CACHE_BYTES = 12 * 1024 * 1024;
const MAX_ITEMS = 256;
const cached = new Map<string, string>();
let bytes = 0;
let running = 0;

type Listener = { resolve: (src: string) => void; reject: (error: unknown) => void };
type Request = { path: string; listeners: Set<Listener> };
const outstanding = new Map<string, Request>();
const waiting: Request[] = [];

function drain() {
  while (running < CONCURRENCY && waiting.length) {
    const request = waiting.shift()!;
    if (outstanding.get(request.path) !== request) continue;
    running++;
    void Promise.resolve().then(() => imageUrl(request.path)).then(src => {
      if (!request.listeners.size) return;
      // Count a conservative two bytes per JS code unit.
      const weight = src.length * 2;
      if (weight <= MAX_CACHE_BYTES) {
        cached.set(request.path, src);
        bytes += weight;
        while (bytes > MAX_CACHE_BYTES || cached.size > MAX_ITEMS) {
          const key = cached.keys().next().value!;
          bytes -= cached.get(key)!.length * 2;
          cached.delete(key);
        }
      }
      for (const listener of request.listeners) listener.resolve(src);
    }, error => {
      for (const listener of request.listeners) listener.reject(error);
    }).finally(() => {
      outstanding.delete(request.path);
      running--;
      drain();
    });
  }
}

export function requestThumbnail(path: string, size: ThumbnailSize, listener: Listener): () => void {
  const key = path + (path.includes("?") ? "&" : "?") + "thumbnail=" + size;
  const src = cached.get(key);
  if (src !== undefined) {
    cached.delete(key);
    cached.set(key, src);
    listener.resolve(src);
    return () => {};
  }

  let request = outstanding.get(key);
  if (!request) {
    request = { path: key, listeners: new Set() };
    outstanding.set(key, request);
    waiting.push(request);
  }
  request.listeners.add(listener);
  drain();
  return () => {
    request.listeners.delete(listener);
    if (request.listeners.size) return;
    const index = waiting.indexOf(request);
    if (index !== -1) {
      waiting.splice(index, 1);
      outstanding.delete(key);
    }
  };
}
