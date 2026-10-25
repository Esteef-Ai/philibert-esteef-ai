// Philibert's Group Board server: the shared place a group's Philibert drives post to.
//
// Everything lives in Netlify Blobs, one object per thing, so two people posting at once
// never overwrite each other (no counters, no read-modify-write):
//   inv/<code>                     -> {gid}                    invite code
//   tok/<sha256(token)>            -> {gid, mid}               a member's key
//   g/<gid>/meta                   -> {name, ntfy, created}
//   g/<gid>/m/<mid>                -> {name, admin, token_hash, joined}
//   g/<gid>/th/<tid>               -> thread {title, by, at, pinned, poll}
//   g/<gid>/p/<tid>/<ts>-<pid>     -> post {body, by, at, files, deleted}
//   g/<gid>/v/<tid>/<mid>          -> {options: [i...]}          a member's poll vote
//   g/<gid>/a/<ts>-<pid>           -> activity (what "new since" reads)
//   g/<gid>/f/<fid>                -> attachment meta;  files store: <gid>/<fid> -> bytes
// Members sign in with the token they got when they created or joined the group
// (Authorization: Bearer). New threads and replies also go to the group's ntfy topic.
import type { Config, Context } from "@netlify/functions"
import { getStore } from "@netlify/blobs"

const MAX_FILE = 5 * 1024 * 1024
const db = () => getStore({ name: "board", consistency: "strong" })
const fs = () => getStore({ name: "board-files", consistency: "strong" })

type Json = Record<string, any>
const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } })
const bad = (status: number, error: string) => json(status, { error })
const clean = (s: unknown, max: number) => String(s ?? "").replace(/\r\n?/g, "\n").trim().slice(0, max)
const ts = (n = Date.now()) => String(n).padStart(13, "0")

function rand(n: number, alphabet = "abcdefghijkmnpqrstuvwxyz23456789") {
  const b = crypto.getRandomValues(new Uint8Array(n))
  return Array.from(b, (x) => alphabet[x % alphabet.length]).join("")
}
async function sha256(s: string) {
  const h = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s))
  return Array.from(new Uint8Array(h), (x) => x.toString(16).padStart(2, "0")).join("")
}
const get = (k: string) => db().get(k, { type: "json" }) as Promise<Json | null>
const put = (k: string, v: unknown) => db().setJSON(k, v)
async function keys(prefix: string) {
  const { blobs } = await db().list({ prefix })
  return blobs.map((b) => b.key)
}

async function newMember(gid: string, name: string, admin: boolean) {
  const mid = rand(10), token = rand(40, "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
  const th = await sha256(token)
  await put(`g/${gid}/m/${mid}`, { name, admin, token_hash: th, joined: Date.now() })
  await put(`tok/${th}`, { gid, mid })
  return { mid, token }
}

async function members(gid: string) {
  const out: Json[] = []
  for (const k of await keys(`g/${gid}/m/`)) {
    const m = await get(k)
    if (m) out.push({ id: k.split("/").pop(), name: m.name, admin: !!m.admin, joined: m.joined })
  }
  return out
}

async function threadSummaries(gid: string) {
  const posts = await keys(`g/${gid}/p/`)            // g/<gid>/p/<tid>/<ts>-<pid>
  const stats: Record<string, { n: number; last: number }> = {}
  for (const k of posts) {
    const [, , , tid, leaf] = k.split("/")
    const t = Number(leaf.split("-")[0])
    const s = (stats[tid] ||= { n: 0, last: 0 })
    s.n += 1
    s.last = Math.max(s.last, t)
  }
  const out: Json[] = []
  for (const k of await keys(`g/${gid}/th/`)) {
    const tid = k.split("/").pop()!
    const t = await get(k)
    if (!t || t.deleted) continue
    const s = stats[tid] || { n: 0, last: t.at }
    out.push({ id: tid, title: t.title, by: t.by, at: t.at, pinned: !!t.pinned, poll: !!t.poll,
               replies: Math.max(0, s.n - 1), last: Math.max(s.last, t.at) })
  }
  return out.sort((a, b) => Number(b.pinned) - Number(a.pinned) || b.last - a.last)
}

async function thread(gid: string, tid: string, mid: string) {
  const t = await get(`g/${gid}/th/${tid}`)
  if (!t || t.deleted) return null
  const posts: Json[] = []
  for (const k of (await keys(`g/${gid}/p/${tid}/`)).sort()) {
    const p = await get(k)
    if (p) posts.push({ id: k.split("/").pop(), ...p, body: p.deleted ? "" : p.body, files: p.deleted ? [] : p.files || [] })
  }
  let poll = null
  if (t.poll) {
    const counts = t.poll.options.map(() => 0)
    let mine: number[] = []
    const voters: Record<number, string[]> = {}
    const names = Object.fromEntries((await members(gid)).map((m) => [m.id, m.name]))
    for (const k of await keys(`g/${gid}/v/${tid}/`)) {
      const v = await get(k), who = k.split("/").pop()!
      for (const i of v?.options || []) {
        if (i >= 0 && i < counts.length) { counts[i] += 1; (voters[i] ||= []).push(names[who] || "?") }
      }
      if (who === mid) mine = v?.options || []
    }
    poll = { ...t.poll, counts, mine, voters, closed: !!(t.poll.closes && Date.now() > t.poll.closes) }
  }
  return { id: tid, title: t.title, by: t.by, at: t.at, pinned: !!t.pinned, posts, poll }
}

async function addPost(gid: string, tid: string, mid: string, by: string, body: string, files: Json[]) {
  const at = Date.now(), pid = rand(8)
  await put(`g/${gid}/p/${tid}/${ts(at)}-${pid}`, { body, by, by_id: mid, at, files })
  await put(`g/${gid}/a/${ts(at)}-${pid}`, { tid, pid, by, by_id: mid, at })
  return { id: `${ts(at)}-${pid}`, at }
}

function alert(context: Context, topic: string, group: string, title: string, message: string, click?: string) {
  if (!topic) return
  context.waitUntil(fetch("https://ntfy.sh/", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ topic, title: `${group}: ${title}`.slice(0, 120), message: message.slice(0, 200), tags: ["speech_balloon"],
                           ...(click ? { click } : {}) }),
  }).catch(() => {}))
}

async function files(gid: string, ids: unknown) {
  const out: Json[] = []
  for (const id of Array.isArray(ids) ? ids.slice(0, 10) : []) {
    const f = await get(`g/${gid}/f/${String(id).replace(/[^a-z0-9]/g, "")}`)
    if (f) out.push({ id: f.id, name: f.name, type: f.type, size: f.size })
  }
  return out
}

export default async (req: Request, context: Context) => {
  const url = new URL(req.url)
  const path = url.pathname.replace(/^\/api\/?/, "").split("/").filter(Boolean)
  const method = req.method
  if (!path.length) return json(200, { ok: true, service: "philibert-board" })

  // -- no sign-in: create a group, or join one with its invite code
  if (method === "POST" && (path[0] === "groups" || path[0] === "join")) {
    let d: Json
    try { d = await req.json() } catch { return bad(400, "Send JSON.") }
    const name = clean(d.name, 40)
    if (name.length < 1) return bad(400, "Say what to call you.")
    let gid: string, admin = false
    if (path[0] === "groups") {
      const gname = clean(d.group_name, 60)
      if (gname.length < 2) return bad(400, "Give the group a name.")
      gid = rand(12)
      const invite = rand(8, "ABCDEFGHJKLMNPQRSTUVWXYZ23456789")
      await put(`g/${gid}/meta`, { name: gname, invite, ntfy: "philibert-" + rand(24), created: Date.now() })
      await put(`inv/${invite}`, { gid })
      admin = true
    } else {
      const inv = await get(`inv/${clean(d.invite, 20).toUpperCase().replace(/[^A-Z0-9]/g, "")}`)
      if (!inv) return bad(404, "That invite code doesn't match a group.")
      gid = inv.gid
    }
    const { mid, token } = await newMember(gid, name, admin)
    const g = (await get(`g/${gid}/meta`))!
    return json(201, { group: { id: gid, name: g.name, invite: g.invite, ntfy: g.ntfy }, member: { id: mid, name, admin }, token })
  }

  // -- everything else: a member's token
  const auth = (req.headers.get("authorization") || "").replace(/^Bearer\s+/i, "")
  const who = auth ? await get(`tok/${await sha256(auth)}`) : null
  if (!who) return bad(401, "Not a member of a group (sign in again with an invite code).")
  const { gid, mid } = who as { gid: string; mid: string }
  const me = await get(`g/${gid}/m/${mid}`)
  const g = await get(`g/${gid}/meta`)
  if (!me || !g) return bad(401, "This membership has ended.")

  if (method === "GET" && path[0] === "me")
    return json(200, { group: { id: gid, name: g.name, invite: g.invite, ntfy: g.ntfy },
                       member: { id: mid, name: me.name, admin: !!me.admin }, members: await members(gid) })

  if (method === "GET" && path[0] === "threads" && path.length === 1) return json(200, { threads: await threadSummaries(gid) })

  if (method === "GET" && path[0] === "threads" && path[1]) {
    const t = await thread(gid, path[1], mid)
    return t ? json(200, t) : bad(404, "That thread is gone.")
  }

  if (method === "GET" && path[0] === "changes") {
    const since = Number(url.searchParams.get("since") || 0)
    const recent = (await keys(`g/${gid}/a/`)).filter((k) => Number(k.split("/").pop()!.split("-")[0]) > since).sort().slice(-50)
    const items: Json[] = []
    const titles: Record<string, string> = {}
    for (const k of recent) {
      const a = await get(k)
      if (!a || a.by_id === mid) continue                          // your own posts don't notify you
      titles[a.tid] ||= (await get(`g/${gid}/th/${a.tid}`))?.title || ""
      items.push({ ...a, title: titles[a.tid] })
    }
    return json(200, { items, now: Date.now() })
  }

  if (method === "POST" && path[0] === "threads" && path.length === 1) {
    const d = await req.json().catch(() => ({}))
    const title = clean(d.title, 120), body = clean(d.body, 10000)
    if (title.length < 2) return bad(400, "Give the post a title.")
    let poll = null
    if (d.poll && Array.isArray(d.poll.options)) {
      const options = d.poll.options.map((o: unknown) => clean(o, 100)).filter(Boolean).slice(0, 10)
      if (options.length < 2) return bad(400, "A poll needs at least two choices.")
      poll = { question: clean(d.poll.question, 200) || title, options, multi: !!d.poll.multi,
               closes: Number(d.poll.closes) > Date.now() ? Number(d.poll.closes) : null }
    }
    if (!body && !poll) return bad(400, "Write something, or add a poll.")
    const tid = ts() + rand(4)
    await put(`g/${gid}/th/${tid}`, { title, by: me.name, by_id: mid, at: Date.now(), pinned: false, poll })
    await addPost(gid, tid, mid, me.name, body, await files(gid, d.files))
    alert(context, g.ntfy, g.name, `${me.name} posted${poll ? " a poll" : ""}`, title)
    return json(201, { id: tid })
  }

  if (method === "POST" && path[0] === "threads" && path[2] === "posts") {
    const t = await get(`g/${gid}/th/${path[1]}`)
    if (!t || t.deleted) return bad(404, "That thread is gone.")
    const d = await req.json().catch(() => ({}))
    const body = clean(d.body, 10000), fl = await files(gid, d.files)
    if (!body && !fl.length) return bad(400, "Write something first.")
    const p = await addPost(gid, path[1], mid, me.name, body, fl)
    alert(context, g.ntfy, g.name, `${me.name} replied`, `${t.title}: ${body}`)
    return json(201, p)
  }

  if (method === "POST" && path[0] === "threads" && path[2] === "vote") {
    const t = await get(`g/${gid}/th/${path[1]}`)
    if (!t?.poll) return bad(404, "No poll there.")
    if (t.poll.closes && Date.now() > t.poll.closes) return bad(400, "That poll has closed.")
    const d = await req.json().catch(() => ({}))
    let opts = (Array.isArray(d.options) ? d.options : []).map(Number).filter((i: number) => i >= 0 && i < t.poll.options.length)
    opts = [...new Set(opts)]
    if (!t.poll.multi) opts = opts.slice(0, 1)
    if (opts.length) await put(`g/${gid}/v/${path[1]}/${mid}`, { options: opts, at: Date.now() })
    else await db().delete(`g/${gid}/v/${path[1]}/${mid}`)
    return json(200, { ok: true })
  }

  if (method === "POST" && path[0] === "threads" && path[2] === "pin") {
    if (!me.admin) return bad(403, "Only the group's admin can pin.")
    const t = await get(`g/${gid}/th/${path[1]}`)
    if (!t) return bad(404, "That thread is gone.")
    await put(`g/${gid}/th/${path[1]}`, { ...t, pinned: !t.pinned })
    return json(200, { pinned: !t.pinned })
  }

  if (method === "DELETE" && path[0] === "threads" && path[2] === "posts" && path[3]) {
    const k = `g/${gid}/p/${path[1]}/${path[3].replace(/[^0-9a-z-]/g, "")}`
    const p = await get(k)
    if (!p) return bad(404, "That post is gone.")
    if (p.by_id !== mid && !me.admin) return bad(403, "You can only delete your own posts.")
    await put(k, { ...p, deleted: true, body: "", files: [] })
    const first = (await keys(`g/${gid}/p/${path[1]}/`)).sort()[0]
    if (first === k) {                                             // deleting the opening post removes the thread
      const t = await get(`g/${gid}/th/${path[1]}`)
      if (t) await put(`g/${gid}/th/${path[1]}`, { ...t, deleted: true })
    }
    return json(200, { ok: true })
  }

  if (method === "POST" && path[0] === "files") {
    const name = clean(url.searchParams.get("name"), 120).replace(/[\\/]/g, "_") || "file"
    const type = clean(url.searchParams.get("type"), 100) || "application/octet-stream"
    const buf = await req.arrayBuffer()
    if (!buf.byteLength) return bad(400, "That file is empty.")
    if (buf.byteLength > MAX_FILE) return bad(413, "Files can be up to 5 MB.")
    const fid = rand(16)
    await fs().set(`${gid}/${fid}`, buf, { metadata: { name, type } })
    await put(`g/${gid}/f/${fid}`, { id: fid, name, type, size: buf.byteLength, by: me.name, at: Date.now() })
    return json(201, { id: fid, name, type, size: buf.byteLength })
  }

  if (method === "GET" && path[0] === "files" && path[1]) {
    const fid = path[1].replace(/[^a-z0-9]/g, "")
    const f = await get(`g/${gid}/f/${fid}`)
    const data = f ? await fs().get(`${gid}/${fid}`, { type: "arrayBuffer" }) : null
    if (!f || !data) return bad(404, "That file is gone.")
    return new Response(data, { headers: { "content-type": f.type,
      "content-disposition": `attachment; filename="${encodeURIComponent(f.name)}"` } })
  }

  return bad(404, "No such thing.")
}

export const config: Config = {
  path: "/api/*",
  // a drive checks for news once a minute; this leaves plenty of room for real use
  rateLimit: { windowLimit: 120, windowSize: 60, aggregateBy: ["ip", "domain"] },
}
