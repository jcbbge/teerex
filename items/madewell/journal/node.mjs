// Made Well's journal node: serves one `journal` actor per run on the work engine.
// Each actor keeps that run's saved returns in its own SQLite: an append-only list of
// journal records and the content blobs they point at. It holds only its node token.
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { homedir } from "node:os";
import { actor, setup } from "rivetkit";
import { db } from "rivetkit/db";

const env = (name, fallback) => process.env[name] || fallback;
const credentials = env("MW_JOURNAL_CREDENTIALS",
  `${homedir()}/.local/share/agent-credentials/madewell-journal`);
const token = readFileSync(`${credentials}/node.token`, "utf8").trim();
if (!token) throw new Error(`empty node token in ${credentials}/node.token`);

const SHA = /^[0-9a-f]{64}$/;
const reply = (status, body, type = "application/json") =>
  new Response(body, { status, headers: { "content-type": type, "cache-control": "no-store" } });
const fail = (status, message) => reply(status, JSON.stringify({ error: message }));

const journal = actor({
  options: { name: "Made Well journal" },
  db: db({
    onMigrate: async (sql) => {
      await sql.execute(`CREATE TABLE IF NOT EXISTS records (
        seq INTEGER PRIMARY KEY AUTOINCREMENT, line TEXT NOT NULL)`);
      await sql.execute(`CREATE TABLE IF NOT EXISTS blobs (
        sha TEXT PRIMARY KEY, bytes BLOB NOT NULL)`);
    },
  }),
  actions: {},
  onRequest: async (c, request) => {
    const path = new URL(request.url).pathname.replace(/^\/request/, "");
    const method = request.method;
    if (method === "GET" && path === "/records") {
      const rows = await c.db.execute("SELECT line FROM records ORDER BY seq");
      return reply(200, rows.map((row) => row.line + "\n").join(""), "application/x-ndjson");
    }
    if (method === "POST" && path === "/records") {
      const line = await request.text();
      let record;
      try { record = JSON.parse(line); } catch { return fail(400, "record is not JSON"); }
      if (line.includes("\n") || typeof record !== "object" || record === null
        || typeof record.key !== "string" || typeof record.fn !== "string"
        || typeof record.input_sha !== "string" || typeof record.attempt !== "number"
        || !["started", "returned", "failed"].includes(record.state)) {
        return fail(400, "invalid journal record");
      }
      const [row] = await c.db.execute(
        "INSERT INTO records (line) VALUES (?) RETURNING seq", line);
      return reply(200, JSON.stringify({ seq: row.seq }));
    }
    const blob = path.match(/^\/blobs\/([0-9a-f]+)$/);
    if (blob && SHA.test(blob[1])) {
      const sha = blob[1];
      if (method === "PUT") {
        const bytes = new Uint8Array(await request.arrayBuffer());
        const actual = createHash("sha256").update(bytes).digest("hex");
        if (actual !== sha) return fail(400, `blob hashes to ${actual}, not ${sha}`);
        await c.db.execute("INSERT OR IGNORE INTO blobs (sha, bytes) VALUES (?, ?)", sha, bytes);
        return reply(200, JSON.stringify({ sha }));
      }
      if (method === "GET") {
        const [row] = await c.db.execute("SELECT bytes FROM blobs WHERE sha = ?", sha);
        if (!row) return fail(404, `no blob ${sha}`);
        return reply(200, Uint8Array.from(row.bytes), "application/octet-stream");
      }
    }
    return fail(404, `no route ${method} ${path}`);
  },
});

const app = setup({
  endpoint: env("MW_JOURNAL_ENDPOINT", "http://127.0.0.1:7420"),
  namespace: env("MW_JOURNAL_NAMESPACE", "madewell-journal"),
  token,
  node: { poolName: env("MW_JOURNAL_POOL", "journal") },
  use: { journal },
});
await app.startAndWait();
console.log(`Made Well journal node connected: namespace ${env("MW_JOURNAL_NAMESPACE", "madewell-journal")}, pool ${env("MW_JOURNAL_POOL", "journal")}`);
