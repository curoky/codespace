'use strict';

const http = require('node:http');

const backendHost = '127.0.0.1';
const backendPort = 8081;
const listenHost = '0.0.0.0';
const listenPort = 8080;
const externalUrl = process.env.APP_URL;
const email = process.env.LOBEHUB_AUTO_AUTH_EMAIL;
const password = process.env.LOBEHUB_AUTO_AUTH_PASSWORD;
const cookiePrefix = process.env.AUTH_COOKIE_PREFIX || 'codespace-lobehub';
const refreshIntervalMs = 24 * 60 * 60 * 1000;

if (!externalUrl) {
  throw new Error('APP_URL is required');
}
const appUrl = new URL(externalUrl);
if (
  !['http:', 'https:'].includes(appUrl.protocol) ||
  appUrl.username ||
  appUrl.password ||
  appUrl.pathname !== '/' ||
  appUrl.search ||
  appUrl.hash
) {
  throw new Error('APP_URL must be an HTTP(S) origin without credentials, path, query, or fragment');
}

if (!email || !password) {
  throw new Error('LOBEHUB_AUTO_AUTH_EMAIL and LOBEHUB_AUTO_AUTH_PASSWORD are required');
}

const readResponse = (response) =>
  new Promise((resolve, reject) => {
    const chunks = [];
    let size = 0;

    response.on('data', (chunk) => {
      size += chunk.length;
      if (size > 1024 * 1024) {
        reject(new Error('authentication response exceeds 1 MiB'));
        response.destroy();
        return;
      }
      chunks.push(chunk);
    });
    response.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')));
    response.on('error', reject);
  });

const jsonRequest = (path, body, cookie) =>
  new Promise((resolve, reject) => {
    const payload = Buffer.from(JSON.stringify(body));
    const headers = {
      'content-length': payload.length,
      'content-type': 'application/json',
      host: appUrl.host,
      origin: appUrl.origin,
      'x-forwarded-host': appUrl.host,
      'x-forwarded-proto': appUrl.protocol.slice(0, -1),
    };
    if (cookie) headers.cookie = cookie;

    const request = http.request(
      {
        headers,
        host: backendHost,
        method: 'POST',
        path,
        port: backendPort,
      },
      async (response) => {
        try {
          resolve({
            body: await readResponse(response),
            setCookies: response.headers['set-cookie'] || [],
            status: response.statusCode || 500,
          });
        } catch (error) {
          reject(error);
        }
      },
    );

    request.on('error', reject);
    request.end(payload);
  });

const authRequest = (path, body) => jsonRequest(path, body);

const sessionCookies = (setCookies) => {
  const cookies = setCookies
    .map((cookie) => cookie.split(';', 1)[0])
    .filter((cookie) => {
      const name = cookie.slice(0, cookie.indexOf('='));
      return name === `${cookiePrefix}.session_token` ||
        name === `__Secure-${cookiePrefix}.session_token` ||
        name === `${cookiePrefix}.session_data` ||
        name === `__Secure-${cookiePrefix}.session_data`;
    });

  if (!cookies.some((cookie) => cookie.includes('.session_token='))) {
    throw new Error('Better Auth did not return a session token cookie');
  }

  return {
    header: cookies.join('; '),
    names: new Set(cookies.map((cookie) => cookie.split('=', 1)[0])),
  };
};

const responseError = (action, response) => {
  const body = response.body.replaceAll(/\s+/g, ' ').slice(0, 300);
  return `${action} failed with HTTP ${response.status}${body ? `: ${body}` : ''}`;
};

const createSession = async () => {
  const credentials = { callbackURL: `${appUrl.origin}/`, email, password };
  let response = await authRequest('/api/auth/sign-in/email', credentials);

  if (response.status < 200 || response.status >= 300) {
    response = await authRequest('/api/auth/sign-up/email', {
      ...credentials,
      name: 'Codespace',
    });
  }

  if (response.status < 200 || response.status >= 300) {
    response = await authRequest('/api/auth/sign-in/email', credentials);
  }

  if (response.status < 200 || response.status >= 300) {
    throw new Error(responseError('automatic authentication', response));
  }

  return {
    ...sessionCookies(response.setCookies),
    refreshAt: Date.now() + refreshIntervalMs,
    setCookies: response.setCookies,
  };
};

let authState;
let initialized = false;
let refreshPromise;

const finishOnboarding = async (state) => {
  const response = await jsonRequest(
    '/trpc/lambda/user.updateOnboarding?batch=1',
    {
      0: {
        json: {
          currentStep: 4,
          finishedAt: new Date().toISOString(),
          version: 2,
        },
      },
    },
    state.header,
  );

  if (response.status < 200 || response.status >= 300) {
    throw new Error(responseError('automatic onboarding', response));
  }
};

const getAuthState = async () => {
  if (authState && Date.now() < authState.refreshAt) return authState;

  refreshPromise ||= createSession()
    .then(async (state) => {
      if (!initialized) {
        await finishOnboarding(state);
        initialized = true;
      }
      authState = state;
      console.log(`automatic LobeHub session ready for ${email}`);
      return state;
    })
    .finally(() => {
      refreshPromise = undefined;
    });

  return refreshPromise;
};

const mergeCookies = (incoming, state) => {
  const retained = (incoming || '')
    .split(';')
    .map((cookie) => cookie.trim())
    .filter(Boolean)
    .filter((cookie) => !state.names.has(cookie.split('=', 1)[0]));

  return [...retained, state.header].join('; ');
};

const isBlockedAuthMutation = (request) => {
  const pathname = new URL(request.url || '/', appUrl).pathname;
  return request.method !== 'GET' && pathname.startsWith('/api/auth/');
};

const forwardedHeaders = (request, state) => {
  const headers = { ...request.headers };
  const remoteAddress = request.socket.remoteAddress;

  headers.cookie = mergeCookies(request.headers.cookie, state);
  headers.host = appUrl.host;
  headers['x-forwarded-host'] = appUrl.host;
  headers['x-forwarded-proto'] = appUrl.protocol.slice(0, -1);
  if (remoteAddress) {
    headers['x-forwarded-for'] = request.headers['x-forwarded-for']
      ? `${request.headers['x-forwarded-for']}, ${remoteAddress}`
      : remoteAddress;
  }

  return headers;
};

const proxyRequest = async (request, response) => {
  if (isBlockedAuthMutation(request)) {
    response.writeHead(403, { 'content-type': 'application/json' });
    response.end('{"error":"authentication is managed by codespace"}\n');
    return;
  }

  try {
    const state = await getAuthState();
    const upstream = http.request(
      {
        headers: forwardedHeaders(request, state),
        host: backendHost,
        method: request.method,
        path: request.url,
        port: backendPort,
      },
      (upstreamResponse) => {
        const headers = { ...upstreamResponse.headers };
        headers['set-cookie'] = [
          ...(upstreamResponse.headers['set-cookie'] || []),
          ...state.setCookies,
        ];
        response.writeHead(upstreamResponse.statusCode || 502, headers);
        upstreamResponse.pipe(response);
      },
    );

    upstream.on('error', (error) => {
      console.error('LobeHub upstream request failed:', error.message);
      if (!response.headersSent) response.writeHead(502);
      response.end('Bad Gateway\n');
    });
    request.on('aborted', () => upstream.destroy());
    request.pipe(upstream);
  } catch (error) {
    console.error('LobeHub automatic authentication failed:', error.message);
    response.writeHead(503);
    response.end('Service Unavailable\n');
  }
};

const server = http.createServer(proxyRequest);

server.on('upgrade', async (request, socket, head) => {
  try {
    const state = await getAuthState();
    const upstream = http.request({
      headers: forwardedHeaders(request, state),
      host: backendHost,
      method: request.method,
      path: request.url,
      port: backendPort,
    });

    upstream.on('upgrade', (upstreamResponse, upstreamSocket, upstreamHead) => {
      const status = upstreamResponse.statusCode || 101;
      const statusMessage = upstreamResponse.statusMessage || 'Switching Protocols';
      const headers = Object.entries(upstreamResponse.headers)
        .flatMap(([name, value]) =>
          (Array.isArray(value) ? value : [value]).map((item) => `${name}: ${item}`),
        )
        .join('\r\n');

      socket.write(`HTTP/1.1 ${status} ${statusMessage}\r\n${headers}\r\n\r\n`);
      if (upstreamHead.length > 0) socket.write(upstreamHead);
      if (head.length > 0) upstreamSocket.write(head);
      upstreamSocket.pipe(socket);
      socket.pipe(upstreamSocket);
    });
    upstream.on('response', (upstreamResponse) => {
      socket.end(`HTTP/1.1 ${upstreamResponse.statusCode || 502} Bad Gateway\r\n\r\n`);
    });
    upstream.on('error', () => socket.destroy());
    upstream.end();
  } catch {
    socket.destroy();
  }
});

server.on('clientError', (_error, socket) => socket.end('HTTP/1.1 400 Bad Request\r\n\r\n'));

getAuthState()
  .then(() => {
    server.listen(listenPort, listenHost, () => {
      console.log(
        `LobeHub automatic authentication proxy listening on ${listenHost}:${listenPort}`,
      );
    });
  })
  .catch((error) => {
    console.error('LobeHub automatic authentication bootstrap failed:', error.message);
    process.exitCode = 1;
  });

const shutdown = () => server.close(() => process.exit(0));
process.on('SIGINT', shutdown);
process.on('SIGTERM', shutdown);
