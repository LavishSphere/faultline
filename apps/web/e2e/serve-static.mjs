// Minimal static file server for the e2e smoke test: serves the `next build` static export in `out/` the way
// static hosting does (trailingSlash export: `/cascade/` → `out/cascade/index.html`, unknown paths → `out/404.html`).
// No dependency, no directory listings, no paths outside `out/`. Usage: node e2e/serve-static.mjs <port> [dir]
import { createReadStream, statSync } from "node:fs";
import { createServer } from "node:http";
import { extname, join, normalize, resolve, sep } from "node:path";

const port = Number(process.argv[2] ?? "3799");
const root = resolve(process.argv[3] ?? "out");

const TYPES = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".txt": "text/plain; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".ico": "image/x-icon",
  ".woff": "font/woff",
  ".woff2": "font/woff2",
  ".ttf": "font/ttf",
  ".map": "application/json; charset=utf-8",
};

function fileAt(path) {
  try {
    return statSync(path).isFile() ? path : null;
  } catch {
    return null;
  }
}

function resolveRequest(urlPath) {
  let decoded;
  try {
    decoded = decodeURIComponent(urlPath);
  } catch {
    return null;
  }
  const target = normalize(join(root, decoded));
  if (target !== root && !target.startsWith(root + sep)) return null;
  return fileAt(join(target, "index.html")) ?? fileAt(target) ?? fileAt(`${target}.html`);
}

const server = createServer((req, res) => {
  if (req.method !== "GET" && req.method !== "HEAD") {
    res.writeHead(405).end();
    return;
  }
  const urlPath = (req.url ?? "/").split("?")[0] ?? "/";
  const found = resolveRequest(urlPath);
  const file = found ?? fileAt(join(root, "404.html"));
  if (!file) {
    res.writeHead(404, { "Content-Type": "text/plain" }).end("not found");
    return;
  }
  res.writeHead(found ? 200 : 404, {
    "Content-Type": TYPES[extname(file)] ?? "application/octet-stream",
    "Cache-Control": "no-store",
  });
  if (req.method === "HEAD") res.end();
  else createReadStream(file).pipe(res);
});

server.listen(port, "127.0.0.1", () => {
  console.log(`static export ${root} on http://127.0.0.1:${port}`);
});
