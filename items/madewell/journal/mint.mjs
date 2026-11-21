// Mint the journal's two scoped tokens and write them 0600 into the credential directory (0700).
// Reads the engine admin token from a file; never prints a token or passes one in argv.
//   node mint.mjs --admin-file <file with TOKEN or KEY=TOKEN line> [--admin-key NAME]
//                 [--endpoint URL] [--namespace NAME] [--pool NAME] [--out DIR] [--duration SECONDS]
//                 [--provision]   create the namespace and pool first if missing
import { chmodSync, mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { parseArgs } from "node:util";

const { values: o } = parseArgs({ options: {
  "admin-file": { type: "string" },
  "admin-key": { type: "string", default: "MADEWELL_ENGINE_ADMIN_TOKEN" },
  endpoint: { type: "string", default: "http://127.0.0.1:7420" },
  namespace: { type: "string", default: "madewell-journal" },
  pool: { type: "string", default: "journal" },
  out: { type: "string", default: `${homedir()}/.local/share/agent-credentials/madewell-journal` },
  duration: { type: "string", default: "86400" },
  provision: { type: "boolean", default: false },
} });
if (!o["admin-file"]) throw new Error("--admin-file is required");

// Grants, narrowest found to work (each tested on a throwaway engine; see journal/README.md).
export const GRANTS = {
  node: [
    { resource: "node", target: "any", operations: ["create"] },
    { resource: "pool", target: "any", operations: ["update"] },
  ],
  library: [
    { resource: "actor", target: "any", operations: ["create"] },
    { resource: "actor_gateway", target: "any", operations: ["read", "create"] },
  ],
};

const raw = readFileSync(o["admin-file"], "utf8");
const line = raw.split("\n").find((l) => l.startsWith(`${o["admin-key"]}=`));
const admin = (line ? line.slice(o["admin-key"].length + 1) : raw).trim();
if (!admin || admin.includes("\n")) throw new Error(`no admin token in ${o["admin-file"]}`);

async function api(path, method = "GET", body) {
  const response = await fetch(o.endpoint + path, {
    method,
    headers: { authorization: `Bearer ${admin}`, "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await response.text();
  if (!response.ok) throw new Error(`${method} ${path}: ${response.status} ${text}`);
  return JSON.parse(text);
}

if (o.provision) {
  const { namespaces } = await api("/namespaces");
  if (!namespaces.some((n) => n.name === o.namespace)) await api("/namespaces", "POST", { name: o.namespace });
  await api(`/pools/${encodeURIComponent(o.pool)}?namespace=${encodeURIComponent(o.namespace)}`, "PUT", {});
}

mkdirSync(o.out, { recursive: true, mode: 0o700 });
chmodSync(o.out, 0o700);
// The node reads its token raw; the library hands curl a header file, so the token never enters argv.
const FILES = { node: ["node.token", (t) => `${t}\n`], library: ["library.header", (t) => `x-rivet-token: ${t}\n`] };
for (const [name, grants] of Object.entries(GRANTS)) {
  const minted = await api("/auth/tokens", "POST", {
    namespace: o.namespace, grants, duration: Number(o.duration), subject: `madewell-journal-${name}`,
  });
  const [file, format] = FILES[name];
  const tmp = `${o.out}/.${file}.tmp`;
  writeFileSync(tmp, format(minted.token), { mode: 0o600 });
  renameSync(tmp, `${o.out}/${file}`);
  console.log(`${name} token written to ${o.out}/${file} (expires ${new Date(minted.expires_ts ?? minted.expiresTs).toISOString()})`);
}
