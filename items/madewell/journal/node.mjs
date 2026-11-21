// Made Well's Rivet runner. Two actors:
//   work    — one per thing Josh wants done: the whole of it (phase, effort, tasks, todos, log, done).
//   journal — one per Made Well script run: its saved returns and blobs.
// It connects to hive's engine with the engine's own admin token from ~/madewell/.env.
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { homedir } from "node:os";
import { actor, setup } from "rivetkit";
import { db } from "rivetkit/db";

const env = (name, fallback) => process.env[name] || fallback;
const envFile = env("MW_ENGINE_ENV", `${homedir()}/madewell/.env`);
const token = (readFileSync(envFile, "utf8").split("\n")
  .find((l) => l.startsWith("MADEWELL_ENGINE_ADMIN_TOKEN=")) || "").slice(28).trim();
if (!token) throw new Error(`no MADEWELL_ENGINE_ADMIN_TOKEN in ${envFile}`);

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


// The thing to be done, whole. GET / returns it. POST / merges a JSON object into it.
// POST /event appends {kind, who, text}. POST /task adds {what}. POST /check sets one task's or plan
// step's done: {list: "tasks" | "plan.<phase>", id, yes, evidence}. done (the work's own) is null until
// checked: {"yes": bool, "evidence": "...", "at": "..."}. plan is pinned at creation from the effort dials.
const PHASES = ["brainstorm", "discovery", "delivery", "land"];
const work = actor({
  options: { name: "Made Well work" },
  db: db({
    onMigrate: async (sql) => {
      await sql.execute("CREATE TABLE IF NOT EXISTS doc (id INTEGER PRIMARY KEY CHECK (id = 1), json TEXT NOT NULL)");
      await sql.execute("CREATE TABLE IF NOT EXISTS log (seq INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, line TEXT NOT NULL)");
    },
  }),
  actions: {},
  onRequest: async (c, request) => {
    const path = new URL(request.url).pathname.replace(/^\/request/, "") || "/";
    const now = new Date().toISOString();
    const [row] = await c.db.execute("SELECT json FROM doc WHERE id = 1");
    const doc = row ? JSON.parse(row.json) : { what: null, phase: "brainstorm", effort: {}, plan: {},
      tasks: [], todos: [], links: [], done: null, created: now };
    const save = async (next) => {
      next.updated = now;
      await c.db.execute("INSERT INTO doc (id, json) VALUES (1, ?) ON CONFLICT(id) DO UPDATE SET json = excluded.json",
        JSON.stringify(next));
      return reply(200, JSON.stringify(next));
    };
    const body = async () => {
      try { const v = JSON.parse(await request.text()); return v && typeof v === "object" && !Array.isArray(v) ? v : null; }
      catch { return null; }
    };
    if (request.method === "GET" && path === "/") {
      const log = (await c.db.execute("SELECT at, line FROM log ORDER BY seq")).map((r) => {
        try { return { at: r.at, ...JSON.parse(r.line) }; } catch { return { at: r.at, kind: "note", text: r.line }; }
      });
      return reply(200, JSON.stringify({ ...doc, log }));
    }
    if (request.method !== "POST") return fail(404, `no route ${request.method} ${path}`);
    if (path === "/log" || path === "/event") {
      const text = await request.text();
      let event;
      try { event = JSON.parse(text); } catch { event = { kind: "note", text: text.trim() }; }
      if (!event || typeof event !== "object" || !event.text) return fail(400, "event needs text");
      await c.db.execute("INSERT INTO log (at, line) VALUES (?, ?)", now, JSON.stringify(event));
      return reply(200, JSON.stringify({ at: now }));
    }
    const patch = await body();
    if (!patch) return fail(400, "body must be a JSON object");
    if (path === "/") {
      if (patch.phase !== undefined && !PHASES.includes(patch.phase)) return fail(400, `phase is one of ${PHASES}`);
      return save({ ...doc, ...patch });
    }
    if (path === "/task") {
      if (!patch.what) return fail(400, "task needs what");
      const tasks = doc.tasks.map((t, i) => typeof t === "string" ? { id: i + 1, what: t, done: null } : t);
      tasks.push({ id: Math.max(0, ...tasks.map((t) => t.id)) + 1, what: patch.what, done: null });
      return save({ ...doc, tasks });
    }
    if (path === "/check") {
      const list = patch.list === "tasks" ? doc.tasks
        : patch.list?.startsWith("plan.") ? doc.plan?.[patch.list.slice(5)] : null;
      const item = list?.find((t) => String(t.id) === String(patch.id));
      if (!item) return fail(404, `no ${patch.list} item ${patch.id}`);
      if (typeof patch.yes !== "boolean" || !patch.evidence) return fail(400, "check needs yes (bool) and evidence");
      item.done = { yes: patch.yes, evidence: patch.evidence, at: now };
      return save(doc);
    }
    return fail(404, `no route POST ${path}`);
  },
});

const app = setup({
  endpoint: env("MW_JOURNAL_ENDPOINT", "http://127.0.0.1:7420"),
  namespace: env("MW_JOURNAL_NAMESPACE", "madewell-journal"),
  token,
  node: { poolName: env("MW_JOURNAL_POOL", "journal") },
  use: { journal, work },
});
await app.startAndWait();
console.log(`Made Well journal node connected: namespace ${env("MW_JOURNAL_NAMESPACE", "madewell-journal")}, pool ${env("MW_JOURNAL_POOL", "journal")}`);
