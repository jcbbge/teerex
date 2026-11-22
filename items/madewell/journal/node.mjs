// Made Well's Rivet runner. Two actors:
//   work    — one per thing Josh wants done: the whole of it (phase, effort, tasks, todos, log, done).
//   journal — one per Made Well script run: its saved returns and blobs.
// It connects to hive's engine with the engine's own admin token from ~/madewell/.env.
import { createHash, timingSafeEqual } from "node:crypto";
import { readFileSync, realpathSync, statSync } from "node:fs";
import { homedir } from "node:os";
import { isAbsolute } from "node:path";
import { actor, setup } from "rivetkit";
import { db } from "rivetkit/db";
import { PHASES, WAKE, checkHand, driveWork, publicDoc, readDoc, serialize, startDrive,
  stopDrive, validPlan, writeDoc } from "./work-driver.mjs";

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


// The work actor is the driver. `go` pins the checkout and arms a named durable schedule.
// Each wake reads the pinned plan and advances its first open step. The scheduled action and
// document writes share an actor-local queue. SQLite commits each transition with its log entry.
// The actor saves the attempt before spawning a detached hand. The hand claims that attempt on
// disk before running a harness and records its process-group identity and exit. After a node
// restart the actor checks that same attempt, so a live hand keeps working and a recorded exit
// is consumed once. The process wrapper owns cleanup, including when the node is down.
// A stop is sticky. Persist it before requesting group reap. Follow the step's expected time
// for stalls, record the reason, reap the group, then try the next entry on the staffing note.
// Exhaustion leaves the step open and opens one decision card. Only an explicit retry starts
// a fresh round. Finishing or stopping cancels the wake after process cleanup is confirmed.
// The thing to be done, whole. GET / returns it. POST / merges a JSON object into it.
// POST /event appends {kind, who, text}. POST /task adds {what}. POST /check sets one task's or plan
// step's done: {list: "tasks" | "plan.<phase>", id, yes, evidence}. done (the work's own) is null until
// checked: {"yes": bool, "evidence": "...", "at": "..."}. plan is pinned at creation from the effort dials.
const controlToken = Buffer.from(token);
const DRIVE_BODY_BYTES = 8192;

function canDrive(request) {
  const supplied = Buffer.from(request.headers.get("x-mw-work-control") ?? "");
  return supplied.length === controlToken.length && timingSafeEqual(supplied, controlToken);
}

async function controlBody(request) {
  const reader = request.body?.getReader();
  if (!reader) return null;
  const chunks = [];
  let bytes = 0;
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    bytes += value.byteLength;
    if (bytes > DRIVE_BODY_BYTES) {
      await reader.cancel();
      return null;
    }
    chunks.push(Buffer.from(value));
  }
  try {
    const body = JSON.parse(Buffer.concat(chunks).toString("utf8"));
    return body && typeof body === "object" && !Array.isArray(body) ? body : null;
  } catch { return null; }
}

async function control(c, route, patch) {
  const doc = await readDoc(c);
  if (typeof doc.what !== "string" || !doc.what.trim()) return fail(404, "work has not been created");
  if (route === "/stop") {
    if (Object.keys(patch).length) return fail(400, "stop accepts an empty object");
    await stopDrive(c, doc, "Stopped on request.");
    return Response.json(publicDoc(doc));
  }
  if (Object.keys(patch).some((key) => !["cwd", "session"].includes(key)) ||
      typeof patch.cwd !== "string" || !isAbsolute(patch.cwd) || patch.cwd.includes("\0") ||
      (patch.session != null && (typeof patch.session !== "string" ||
        !/^session:[a-zA-Z0-9-]+$/.test(patch.session)))) {
    return fail(400, "go needs an absolute checkout path and an optional Rex session");
  }
  if (doc._driver?.status === "stopped") return fail(409, "work was stopped");
  if (doc._driver || doc.done) return Response.json(publicDoc(doc));
  if (!validPlan(doc.plan)) return fail(409, "invalid pinned plan or staffing note");
  let cwd;
  try {
    cwd = realpathSync(patch.cwd);
    if (!statSync(cwd).isDirectory()) return fail(400, "checkout path must be a directory");
  } catch { return fail(400, "checkout path must be a directory"); }
  await startDrive(c, doc, { cwd, session: patch.session });
  return Response.json(publicDoc(doc));
}
const work = actor({
  options: { name: "Made Well work" },
  db: db({
    onMigrate: async (sql) => {
      await sql.execute("CREATE TABLE IF NOT EXISTS doc (id INTEGER PRIMARY KEY CHECK (id = 1), json TEXT NOT NULL)");
      await sql.execute("CREATE TABLE IF NOT EXISTS log (seq INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, line TEXT NOT NULL)");
    },
  }),
  createVars: () => ({ pending: Promise.resolve() }),
  actions: {
    driveWork: (c) => {
      if (c.scheduledFire?.name !== WAKE) throw new Error("work wake requires the actor schedule");
      return serialize(c, () => driveWork(c));
    },
  },
  onRequest: async (c, request) => {
    const path = new URL(request.url).pathname.replace(/^\/request/, "") || "/";
    if (request.method === "POST" && ["/go", "/stop"].includes(path)) {
      if (!canDrive(request)) return fail(403, "work control requires engine admin");
      if (c.key.length !== 1 || !/^[a-zA-Z0-9][a-zA-Z0-9._-]*$/.test(c.key[0])) {
        return fail(400, "work control needs a simple work key");
      }
      const patch = await controlBody(request);
      if (!patch) return fail(400, "work control needs a small JSON object");
      return serialize(c, () => control(c, path, patch));
    }
    return serialize(c, () => workRequest(c, request, path));
  },
});

async function workRequest(c, request, path) {
  const now = new Date().toISOString();
  const doc = await readDoc(c);
  const save = async (next) => {
    await writeDoc(c, next);
    return reply(200, JSON.stringify(publicDoc(next)));
  };
  const body = async () => {
    try { const v = JSON.parse(await request.text()); return v && typeof v === "object" && !Array.isArray(v) ? v : null; }
    catch { return null; }
  };
  if (request.method === "GET" && path === "/") {
    const log = (await c.db.execute("SELECT at, line FROM log ORDER BY seq")).map((r) => {
      try { return { at: r.at, ...JSON.parse(r.line) }; } catch { return { at: r.at, kind: "note", text: r.line }; }
    });
    return reply(200, JSON.stringify({ ...publicDoc(doc), log }));
  }
  if (request.method !== "POST") return fail(404, `no route ${request.method} ${path}`);
  if (doc._driver && !canDrive(request)) return fail(403, "actor-driven work writes require engine admin");
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
  const attempt = request.headers.get("x-mw-work-attempt");
  if (path === "/") {
    if ("_driver" in patch || "driver" in patch || (attempt && "done" in patch)) {
      return fail(403, "driver and hired-hand completion are controlled by the work actor");
    }
    if (patch.plan !== undefined && ["running", "blocked"].includes(doc._driver?.status)) {
      return fail(409, "a driving work pins its plan");
    }
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
    if (typeof patch.yes !== "boolean" || typeof patch.evidence !== "string" || !patch.evidence.trim()) {
      return fail(400, "check needs yes (bool) and evidence");
    }
    if (attempt && typeof patch.list === "string" && patch.list.startsWith("plan.")) {
      if (!await checkHand(c, doc, attempt, patch)) return fail(409, "check is outside this hand's assignment");
      return reply(200, JSON.stringify(publicDoc(doc)));
    }
    const list = patch.list === "tasks" ? doc.tasks
      : typeof patch.list === "string" && patch.list.startsWith("plan.") ? doc.plan?.[patch.list.slice(5)] : null;
    const item = list?.find((t) => String(t.id) === String(patch.id));
    if (!item) return fail(404, `no ${patch.list} item ${patch.id}`);
    item.done = { yes: patch.yes, evidence: patch.evidence, at: now };
    return save(doc);
  }
  return fail(404, `no route POST ${path}`);
}

const app = setup({
  endpoint: env("MW_JOURNAL_ENDPOINT", "http://127.0.0.1:7420"),
  namespace: env("MW_JOURNAL_NAMESPACE", "madewell-journal"),
  token,
  node: { poolName: env("MW_JOURNAL_POOL", "journal") },
  use: { journal, work },
});
await app.startAndWait();
console.log(`Made Well journal node connected: namespace ${env("MW_JOURNAL_NAMESPACE", "madewell-journal")}, pool ${env("MW_JOURNAL_POOL", "journal")}`);
