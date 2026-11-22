import { spawn, spawnSync } from "node:child_process";
import { createHash, randomUUID } from "node:crypto";
import { existsSync, linkSync, mkdirSync, readFileSync, renameSync, rmdirSync, rmSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

export const PHASES = ["brainstorm", "discovery", "delivery", "land"];
export const WAKE = "drive-work";
const WAKE_MS = 5000;
const DEFAULT_STEP_SECONDS = 30 * 60;
const CARD_RETRY_MS = 60_000;
const INSTANCE = randomUUID();
const BOOT = readFileSync("/proc/sys/kernel/random/boot_id", "utf8").trim();
const HOME_STATE = process.env.XDG_STATE_HOME || join(homedir(), ".local/state");
const ITEM = fileURLToPath(new URL("../", import.meta.url));
const PROCESS = fileURLToPath(new URL("./work-process.py", import.meta.url));

export async function readDoc(c) {
  const [row] = await c.db.execute("SELECT json FROM doc WHERE id = 1");
  return row ? JSON.parse(row.json) : {
    what: null, phase: "brainstorm", effort: {}, plan: {},
    tasks: [], todos: [], links: [], done: null, created: new Date().toISOString(),
  };
}

export async function writeDoc(c, doc, event) {
  doc.updated = new Date().toISOString();
  const write = (db) => db.execute(
    "INSERT INTO doc (id, json) VALUES (1, ?) ON CONFLICT(id) DO UPDATE SET json = excluded.json",
    JSON.stringify(doc));
  if (!event) return write(c.db);
  return c.db.transaction(async (tx) => {
    await write(tx);
    await tx.execute("INSERT INTO log (at, line) VALUES (?, ?)", doc.updated,
      JSON.stringify({ who: "work actor", ...event }));
  }, { name: "work transition" });
}

export function publicDoc(doc) {
  const { _driver: driver, ...work } = doc;
  if (driver) work.driver = {
    status: driver.status,
    ...(driver.active?.kind === "hand" ? { phase: driver.active.phase, step: driver.active.step,
      hand: driver.active.label, expectedBy: new Date(driver.active.deadline).toISOString() } : {}),
  };
  return work;
}

// Keep every read-modify-write and wake in the same queue, including checks from a running hand.
export function serialize(c, run) {
  const next = c.vars.pending.then(run);
  c.vars.pending = next.catch(() => {});
  return next;
}

function stepAt(doc, phase, id) {
  return doc.plan?.[phase]?.find((step) => String(step.id) === String(id));
}

function nextStep(doc) {
  for (const phase of PHASES) {
    const step = doc.plan?.[phase]?.find((candidate) => !candidate.done);
    if (step) return { phase, step };
  }
}

function validStaff(who) {
  return who && ["claude", "codex"].includes(who.harness) &&
    typeof who.model === "string" && /^[a-zA-Z0-9][a-zA-Z0-9._:/-]*$/.test(who.model) &&
    typeof who.effort === "string" && /^[a-z][a-z0-9_-]*$/.test(who.effort);
}

function validStep(step) {
  if (!step || typeof step.step !== "string" || !step.step) return false;
  const id = Number.isSafeInteger(step.id) || typeof step.id === "string" && step.id.length > 0;
  const seconds = step.expectedSeconds;
  const deadline = seconds === undefined || Number.isSafeInteger(seconds) && seconds > 0 &&
    seconds <= (8.64e15 - Date.now()) / 1000;
  const staff = step.who === undefined || Array.isArray(step.who) && step.who.every(validStaff);
  return id && deadline && staff && (!step.done || typeof step.done.yes === "boolean");
}

export function validPlan(plan) {
  return plan && typeof plan === "object" && !Array.isArray(plan) &&
    Object.entries(plan).every(([phase, steps]) => PHASES.includes(phase) &&
      Array.isArray(steps) && steps.every(validStep) &&
      new Set(steps.map((step) => String(step.id))).size === steps.length);
}

function directory(c, id) {
  const actor = createHash("sha256").update(c.actorId).digest("hex");
  return join(HOME_STATE, "madewell/work/hands", actor, id);
}

function readJson(path) {
  try { return JSON.parse(readFileSync(path, "utf8")); }
  catch (error) { if (error.code !== "ENOENT") throw error; }
}

function sameLeader(owner) {
  if (owner.boot !== BOOT) return false;
  try {
    const stat = readFileSync(`/proc/${owner.pid}/stat`, "utf8");
    const fields = stat.slice(stat.lastIndexOf(")") + 2).split(" ");
    return fields[0] !== "Z" && fields[19] === owner.start &&
      Number(fields[2]) === owner.pid && Number(fields[3]) === owner.pid;
  } catch (error) {
    if (!["ENOENT", "ESRCH"].includes(error.code)) throw error;
    return false;
  }
}

function launch(c, doc, active, spec) {
  const dir = directory(c, active.id);
  mkdirSync(dir, { recursive: true, mode: 0o700 });
  if (existsSync(join(dir, "pgid")) || existsSync(join(dir, "cancel"))) return;
  const input = join(dir, "launch.json");
  if (!existsSync(input)) {
    const stage = join(dir, "launch.tmp");
    writeFileSync(stage, JSON.stringify(spec), { mode: 0o600 });
    renameSync(stage, input);
  }
  const env = { ...process.env, MW_ENGINE: process.env.MW_JOURNAL_ENDPOINT || "http://127.0.0.1:7420",
    MW_WORK_NAMESPACE: c.namespace, MW_WORK_POOL: process.env.MW_JOURNAL_POOL || "journal",
    REXCONFIG_MADEWELL: ITEM, PATH: `${join(ITEM, "bin")}:${process.env.PATH}` };
  for (const name of ["REX_BLOCK", "REX_SESSION", "LC_REX_BLOCK", "LC_REX_SESSION",
    "AGENT_PANE", "AGENT_SESSION", "MW_HIRED", "MW_HARNESS", "MW_WORK_ATTEMPT"]) delete env[name];
  const cwd = spec.kind === "hand" ? doc._driver.cwd : ITEM;
  const child = spawn("python3", [PROCESS, dir], { cwd, detached: true, stdio: "ignore", env });
  child.on("error", (error) => console.error("Made Well could not start the work process", error.code));
  child.unref();
}

function cancelProcess(c, active) {
  const dir = directory(c, active.id);
  mkdirSync(dir, { recursive: true, mode: 0o700 });
  writeFileSync(join(dir, "cancel"), "", { mode: 0o600 });
  const owner = readJson(join(dir, "pgid"));
  if (!owner) {
    // A launcher may have been born but hasn't claimed the attempt. A cancellation
    // tombstone wins the same atomic claim, or the wrapper sees cancel before starting.
    try {
      const stage = join(dir, "cancel.json");
      writeFileSync(stage, '{"cancelled":true}', { mode: 0o600 });
      linkSync(stage, join(dir, "pgid"));
      return true;
    } catch (error) {
      if (error.code === "EEXIST") return false;
      throw error;
    }
  }
  if (owner.cancelled) return true;
  if (sameLeader(owner)) return false;
  const reap = spawnSync("python3", [PROCESS, dir, "reap"], { timeout: 3000, stdio: "ignore" });
  if (reap.status === 2) return null;
  return reap.status === 0;
}

function clearDirectory(c, active) {
  const dir = directory(c, active.id);
  rmSync(dir, { force: true, recursive: true });
  try { rmdirSync(dirname(dir)); }
  catch (error) { if (!["ENOENT", "ENOTEMPTY"].includes(error.code)) throw error; }
}

async function reapProcess(c, doc) {
  const active = doc._driver.active;
  const cancelled = cancelProcess(c, active);
  if (cancelled === null && !active.reapBlocked) {
    active.reapBlocked = true;
    await writeDoc(c, doc, { kind: "reap-blocked", text: "Could not verify ownership of the remaining process group." });
  }
  return cancelled === true;
}

async function closeProcess(c, doc, event) {
  const driver = doc._driver;
  const active = driver.active;
  driver.cleanup = active.id;
  delete driver.active;
  await writeDoc(c, doc, event);
  clearDirectory(c, active);
}

export async function startDrive(c, doc, { cwd, session }) {
  await c.cron.every({ name: WAKE, interval: WAKE_MS, action: "driveWork", maxHistory: 1 });
  doc._driver = { status: "running", cwd, session };
  await writeDoc(c, doc, { kind: "driver", text: "Started driving the pinned plan." });
}

export async function stopDrive(c, doc, text) {
  const driver = doc._driver ??= {};
  if (driver.status !== "stopped") {
    driver.status = "stopped";
    await writeDoc(c, doc, { kind: "stopped", text });
  }
  await drain(c, doc);
}

async function drain(c, doc) {
  const active = doc._driver?.active;
  if (active) {
    if (!await reapProcess(c, doc)) return;
    await closeProcess(c, doc, { kind: "reaped", text: "Reaped the work process group." });
  }
  await c.cron.delete(WAKE);
}

export async function checkHand(c, doc, attempt, patch) {
  const driver = doc._driver;
  const active = driver?.active;
  if (driver?.status !== "running" || doc.done || active?.kind !== "hand" ||
      attempt !== active.id || patch.list !== `plan.${active.phase}` ||
      String(patch.id) !== String(active.stepId) || active.ending || active.rejected ||
      stepAt(doc, active.phase, active.stepId)?.done || Date.now() >= active.deadline) return false;
  if (patch.yes) {
    stepAt(doc, active.phase, active.stepId).done = {
      yes: true, evidence: patch.evidence, at: new Date().toISOString(),
    };
  } else {
    active.rejected = patch.evidence;
  }
  await writeDoc(c, doc, { kind: "check", who: active.label, yes: patch.yes,
    phase: active.phase, step: active.step, text: patch.evidence });
  return true;
}

async function observeHand(c, doc, active, owner, result) {
  const driver = doc._driver;
  const step = stepAt(doc, active.phase, active.stepId);
  if (!active.ending) {
    const name = `${active.phase}/${active.step} with ${active.label}`;
    if (step.done) active.ending = { kind: "checked", text: `${name} was checked.` };
    else if (active.rejected) active.ending = { kind: "failure", text: `${name} checked no.` };
    else if (result?.kind === "stalled" || !result && Date.now() >= active.deadline) {
      active.ending = { kind: "stalled", text: `${name} reached its expected time without a check.` };
    } else if (result || owner && !sameLeader(owner)) {
      const reason = result?.kind === "exit" ? `exit ${result.code}` : result?.kind ?? "process disappeared";
      active.ending = { kind: "failure", text: `${name} left the step open (${reason}).` };
    }
    if (active.ending) await writeDoc(c, doc, active.ending);
  }
  if (active.ending) {
    if (!await reapProcess(c, doc)) return;
    if (step.done) delete driver.cursor;
    else driver.cursor = { phase: active.phase, stepId: active.stepId, next: active.index + 1 };
    await closeProcess(c, doc, { kind: "reaped", text: `Reaped ${active.label} on ${active.phase}/${active.step}.` });
    return;
  }
  if (!owner) {
    const rows = await c.db.execute(
      "SELECT line FROM log WHERE json_valid(line) AND json_extract(line, '$.kind') IN ('created', 'prompt') ORDER BY seq LIMIT 3");
    launch(c, doc, active, { kind: "hand", key: c.key[0], phase: active.phase, step,
      who: step.who[active.index], label: active.label, deadline: active.deadline,
      doc: { what: doc.what, log: rows.map(({ line }) => JSON.parse(line)) } });
  } else if (active.observer !== INSTANCE) {
    active.observer = INSTANCE;
    await writeDoc(c, doc, { kind: "adopt", text: `Adopted ${active.label} on ${active.phase}/${active.step}.`,
      pgid: owner.pid });
  }
}

async function observeCard(c, doc, active, owner, result) {
  const driver = doc._driver;
  if (!owner) {
    launch(c, doc, active, { kind: "card", key: c.key[0], session: driver.session,
      what: doc.what, step: active.step });
    return;
  }
  if (!result && sameLeader(owner)) return;
  if (!await reapProcess(c, doc)) return;
  let event;
  if (result?.kind === "answer") {
    driver.status = result.retry ? "running" : "stopped";
    delete driver.cursor;
    event = { kind: result.retry ? "answer" : "stopped", text: result.text, receipt: result.receipt };
  } else if (result?.code === 75) {
    driver.askAfter = Date.now() + CARD_RETRY_MS;
    event = { kind: "card-unavailable", text: "Waiting for a Rex sitting to open the decision card." };
  } else {
    driver.askAfter = null;
    event = { kind: "card-closed", text: "The decision card ended without an answer. The work stays blocked." };
  }
  await closeProcess(c, doc, event);
  if (driver.askAfter === null) await drain(c, doc);
}

export async function driveWork(c) {
  const doc = await readDoc(c);
  const driver = doc._driver;
  if (driver?.cleanup) {
    clearDirectory(c, { id: driver.cleanup });
    delete driver.cleanup;
    await writeDoc(c, doc);
  }
  if (!driver || driver.status === "stopped" || driver.status === "done") return drain(c, doc);
  if (doc.done) {
    driver.status = "done";
    await writeDoc(c, doc);
    return drain(c, doc);
  }
  const active = driver.active;
  if (active) {
    const dir = directory(c, active.id);
    const owner = readJson(join(dir, "pgid"));
    const result = readJson(join(dir, "exit"));
    return active.kind === "hand" ? observeHand(c, doc, active, owner, result) :
      observeCard(c, doc, active, owner, result);
  }

  const next = nextStep(doc);
  if (!next) {
    const failed = PHASES.flatMap((phase) => doc.plan[phase] ?? []).filter((step) => !step.done.yes);
    const evidence = failed.length ? `${failed.length} step(s) checked no.` : "Every step checked yes.";
    doc.done = { yes: !failed.length, evidence, at: new Date().toISOString() };
    driver.status = "done";
    await writeDoc(c, doc, { kind: "done", text: evidence });
    return drain(c, doc);
  }
  const { phase, step } = next;
  const cursor = driver.cursor;
  const index = cursor?.phase === phase && cursor.stepId === step.id ? cursor.next : 0;
  if (driver.status === "running" && step.who?.[index]) {
    const who = step.who[index];
    const label = `${who.harness} ${who.model} ${who.effort}`;
    const deadline = Date.now() + (step.expectedSeconds ?? DEFAULT_STEP_SECONDS) * 1000;
    doc.phase = phase;
    driver.active = { kind: "hand", id: randomUUID(), phase, step: step.step, stepId: step.id,
      label, deadline, index, observer: INSTANCE };
    await writeDoc(c, doc, { kind: "hire", text: `${phase}/${step.step} with ${label}.` });
    return observeHand(c, doc, driver.active);
  }
  if (driver.status === "running") {
    driver.status = "blocked";
    driver.askAfter = Date.now();
    await writeDoc(c, doc, { kind: "blocked", text: `Every hand on the staffing note for ${phase}/${step.step} failed.` });
  }
  if (driver.askAfter !== null && Date.now() >= driver.askAfter) {
    driver.active = { kind: "card", id: randomUUID(), step: step.step };
    await writeDoc(c, doc, { kind: "card", text: `Opening the decision for ${phase}/${step.step}.` });
    return observeCard(c, doc, driver.active);
  }
}
