// A stand-in for the backend, for tests that render the whole page. Install `server.fetch` with
// vi.stubGlobal('fetch', server.fetch). Each route is a function that returns (or resolves to) a
// Response; one that never settles is a request that is still in flight. Like a real fetch, a
// request rejects with an AbortError when its signal aborts, unless the route says `ignoreAbort`
// (a response that was already on its way when the page gave up on it).

export function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

export const json = (body, status = 200, headers = {}) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
  });

/** What fetch rejects with when the network gives out: no response at all. */
export const networkError = () => new TypeError('Failed to fetch');

const abortError = () => Object.assign(new Error('The operation was aborted.'), { name: 'AbortError' });

export function createFakeServer() {
  const calls = [];
  const routes = new Map();

  const server = {
    calls,
    /** Answer `path` with `handler(call)`. Later calls replace earlier routes. */
    on(path, handler, { ignoreAbort = false } = {}) {
      routes.set(path, { handler, ignoreAbort });
      return server;
    },
    /** Answer `path` with each handler in turn, then the last one for every call after. */
    sequence(path, handlers, options) {
      let n = 0;
      return server.on(path, (call) => handlers[Math.min(n++, handlers.length - 1)](call), options);
    },
    count: (path) => calls.filter((c) => c.path === path).length,
    callsTo: (path) => calls.filter((c) => c.path === path),
    fetch(url, init = {}) {
      const path = String(url).replace(/^https?:\/\/[^/]+/, '');
      const call = { path, method: init.method || 'GET', body: init.body, signal: init.signal };
      calls.push(call);
      const route = routes.get(path);
      if (!route) return Promise.resolve(json({ detail: `no route for ${path}` }, 404));
      return new Promise((resolve, reject) => {
        if (!route.ignoreAbort) {
          if (init.signal?.aborted) {
            reject(abortError());
            return;
          }
          init.signal?.addEventListener('abort', () => reject(abortError()), { once: true });
        }
        Promise.resolve()
          .then(() => route.handler(call))
          .then(resolve, reject);
      });
    },
  };
  server.fetch = server.fetch.bind(server);
  return server;
}
