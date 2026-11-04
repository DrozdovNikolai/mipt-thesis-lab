const { getDefaultConfig } = require('expo/metro-config');
const http = require('node:http');
const https = require('node:https');
const config = getDefaultConfig(__dirname);
const upstream = new URL(process.env.EXPO_PUBLIC_API_URL || 'https://session.55nord.ru/api');

function proxyApi(req, res) {
  const transport = upstream.protocol === 'https:' ? https : http;
  const headers = { accept: 'application/json' };
  for (const name of ['authorization', 'content-type']) {
    if (req.headers[name]) headers[name] = req.headers[name];
  }
  const outgoing = transport.request({
    protocol: upstream.protocol, hostname: upstream.hostname, port: upstream.port,
    path: upstream.pathname.replace(/\/$/, '') + req.url.slice(4), method: req.method, headers,
  }, incoming => {
    res.writeHead(incoming.statusCode, { 'Content-Type': incoming.headers['content-type'] || 'application/json', 'Cache-Control': 'no-store' });
    incoming.pipe(res);
  });
  outgoing.on('error', () => { if (!res.headersSent) res.writeHead(502); res.end(); });
  req.pipe(outgoing);
}

const enhance = config.server.enhanceMiddleware;
config.server.enhanceMiddleware = (middleware, server) => {
  const next = enhance ? enhance(middleware, server) : middleware;
  return (req, res, done) => req.url?.startsWith('/api/') ? proxyApi(req, res) : next(req, res, done);
};
module.exports = config;

