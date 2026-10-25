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
//   g/<gid>/av/<mid>               -> the band scheduler: {weekly: [{day, start, end}], blackouts: [{from, to, note}]}
//   g/<gid>/ev/<eid>               -> the band calendar: {kind, title, date, start, end, address, notes, by, cancelled}
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

// -- Google Calendar ------------------------------------------------------------------
const G_SCOPES = "https://www.googleapis.com/auth/calendar.app.created https://www.googleapis.com/auth/calendar.freebusy"
const env = (k: string) => Netlify.env.get(k) || ""
const b64 = (u: Uint8Array) => btoa(String.fromCharCode(...u))
const unb64 = (s: string) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0))
async function aesKey() {
  const raw = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(env("TOKEN_KEY")))
  return crypto.subtle.importKey("raw", raw, "AES-GCM", false, ["encrypt", "decrypt"])
}
async function seal(text: string) {
  const iv = crypto.getRandomValues(new Uint8Array(12))
  const ct = new Uint8Array(await crypto.subtle.encrypt({ name: "AES-GCM", iv }, await aesKey(), new TextEncoder().encode(text)))
  return { iv: b64(iv), ct: b64(ct) }
}
async function unseal(box: Json) {
  const pt = await crypto.subtle.decrypt({ name: "AES-GCM", iv: unb64(box.iv) }, await aesKey(), unb64(box.ct))
  return new TextDecoder().decode(pt)
}
function redirectUri(req: Request) { return new URL("/api/google/callback", req.url).toString() }

async function gAccess(gid: string): Promise<{ token: string; g: Json } | null> {
  const g = await get(`g/${gid}/google`)
  if (!g?.refresh) return null
  const r = await fetch("https://oauth2.googleapis.com/token", { method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ client_id: env("GOOGLE_CLIENT_ID"), client_secret: env("GOOGLE_CLIENT_SECRET"),
                                refresh_token: await unseal(g.refresh), grant_type: "refresh_token" }) })
  const d = await r.json().catch(() => ({}))
  if (!r.ok || !d.access_token) {
    await put(`g/${gid}/google`, { ...g, error: `Google sign-in stopped working (${d.error || r.status}) - connect again.` })
    return null
  }
  if (g.error) await put(`g/${gid}/google`, { ...g, error: "" })
  return { token: d.access_token, g }
}
async function gFetch(token: string, url: string, init: RequestInit = {}) {
  const r = await fetch(url, { ...init, headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json", ...(init.headers || {}) } })
  const text = await r.text()
  let body: Json = {}
  try { body = text ? JSON.parse(text) : {} } catch { body = {} }
  return { ok: r.ok, status: r.status, body }
}

// local wall time in a time zone, for an instant
function localParts(t: Date, tz: string) {
  const p = Object.fromEntries(new Intl.DateTimeFormat("en-CA", { timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).formatToParts(t).map((x) => [x.type, x.value]))
  return { date: `${p.year}-${p.month}-${p.day}`, min: Number(p.hour) * 60 + Number(p.minute) }
}
function addMinutes(date: string, hm: string, plus: number) {
  const [h, m] = hm.split(":").map(Number)
  const d = new Date(date + "T00:00:00Z")
  d.setUTCMinutes(h * 60 + m + plus)
  return { date: d.toISOString().slice(0, 10), hm: d.toISOString().slice(11, 16) }
}

async function gEventSync(gid: string, eid: string, ev: Json) {
  const a = await gAccess(gid)
  if (!a || !a.g.calendar) return ev
  const attendees: Json[] = []
  for (const k of await keys(`g/${gid}/av/`)) {
    const av = await get(k)
    if (av?.email) attendees.push({ email: av.email })
  }
  const cal = encodeURIComponent(a.g.calendar), tz = a.g.tz || "UTC"
  const end = ev.end ? { date: ev.date, hm: ev.end } : addMinutes(ev.date, ev.start, 120)
  const maps = ev.address ? "\nDirections: https://www.google.com/maps/dir/?api=1&destination=" + encodeURIComponent(ev.address) : ""
  const body = { summary: ev.title, location: ev.address || undefined, description: (ev.notes || "") + maps + "\n\nBooked in Philibert by " + ev.by,
                 start: { dateTime: `${ev.date}T${ev.start}:00`, timeZone: tz }, end: { dateTime: `${end.date}T${end.hm}:00`, timeZone: tz },
                 attendees, status: ev.cancelled ? "cancelled" : "confirmed" }
  const base = `https://www.googleapis.com/calendar/v3/calendars/${cal}/events`
  let r
  if (ev.gcal_id && ev.cancelled) r = await gFetch(a.token, `${base}/${encodeURIComponent(ev.gcal_id)}?sendUpdates=all`, { method: "DELETE" })
  else if (ev.gcal_id) r = await gFetch(a.token, `${base}/${encodeURIComponent(ev.gcal_id)}?sendUpdates=all`, { method: "PUT", body: JSON.stringify(body) })
  else if (!ev.cancelled) r = await gFetch(a.token, `${base}?sendUpdates=all`, { method: "POST", body: JSON.stringify(body) })
  if (!r) return ev
  const out = { ...ev, gcal_id: r.ok && r.body.id ? r.body.id : ev.gcal_id || "",
                gcal_error: r.ok || r.status === 410 ? "" : `Google Calendar said ${r.status}: ${r.body?.error?.message || ""}`.slice(0, 200) }
  await put(`g/${gid}/ev/${eid}`, out)
  return out
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

  if (method === "GET" && path[0] === "google" && path[1] === "callback") {
    const page = (msg: string, ok: boolean) => new Response(`<!doctype html><meta charset="utf-8"><title>Philibert</title>
<body style="font:16px system-ui;background:#0f172a;color:#d7e3f4;display:grid;place-items:center;height:100vh;margin:0">
<div style="max-width:440px;text-align:center"><h2 style="color:${ok ? "#10b981" : "#f59e0b"}">${ok ? "Connected" : "Not connected"}</h2><p>${msg}</p>
<p style="color:#8ea3c4">You can close this window and go back to Philibert.</p></div>`, { headers: { "content-type": "text/html; charset=utf-8" } })
    const nonce = (url.searchParams.get("state") || "").replace(/[^a-z0-9]/g, "")
    const st = nonce ? await get(`gstate/${nonce}`) : null
    if (nonce) await db().delete(`gstate/${nonce}`)
    if (!st || Date.now() - st.at > 15 * 60 * 1000) return page("That sign-in link has expired - press Connect Google Calendar again.", false)
    if (url.searchParams.get("error")) return page(`Google said: ${clean(url.searchParams.get("error"), 80)}.`, false)
    const tr = await fetch("https://oauth2.googleapis.com/token", { method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ code: url.searchParams.get("code") || "", client_id: env("GOOGLE_CLIENT_ID"), client_secret: env("GOOGLE_CLIENT_SECRET"),
                                  redirect_uri: redirectUri(req), grant_type: "authorization_code" }) })
    const tok = await tr.json().catch(() => ({}))
    if (!tr.ok || !tok.refresh_token) return page(`Google did not hand over a key (${tok.error || tr.status}). Try again.`, false)
    const scopes = String(tok.scope || "")
    if (!scopes.includes("calendar.app.created") || !scopes.includes("calendar.freebusy"))
      return page("Both permissions are needed (the Band calendar, and free/busy) - tick both boxes on Google's page and try again.", false)
    const meta = await get(`g/${st.gid}/meta`)
    const cal = await gFetch(tok.access_token, "https://www.googleapis.com/calendar/v3/calendars",
                             { method: "POST", body: JSON.stringify({ summary: `${meta?.name || "Band"} (Band)`, timeZone: st.tz || "UTC" }) })
    if (!cal.ok) return page(`Could not make the Band calendar (${cal.status}).`, false)
    await put(`g/${st.gid}/google`, { refresh: await seal(tok.refresh_token), calendar: cal.body.id, tz: st.tz || "UTC",
                                      by: st.by, at: Date.now(), error: "" })
    return page(`The "${meta?.name || "Band"} (Band)" calendar is ready in that Google account.`, true)
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
      if (a.tid) titles[a.tid] ||= (await get(`g/${gid}/th/${a.tid}`))?.title || ""
      items.push({ ...a, title: a.title || titles[a.tid] || "" })
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
    alert(context, g.ntfy, g.name, `${me.name} replied`, t.title)     // titles only: ntfy topics are shared secrets on a public server
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

  // -- Google Calendar -------------------------------------------------------------------
  if (path[0] === "google") {
    if (method === "GET" && path[1] === "status") {
      const gg = await get(`g/${gid}/google`)
      return json(200, { configured: !!(env("GOOGLE_CLIENT_ID") && env("GOOGLE_CLIENT_SECRET") && env("TOKEN_KEY")),
                         connected: !!gg?.refresh, tz: gg?.tz || "", by: gg?.by || "", at: gg?.at || 0, error: gg?.error || "" })
    }
    if (method === "POST" && path[1] === "start") {
      if (!me.admin) return bad(403, "Only the group's admin can connect the band's Google account.")
      if (!env("GOOGLE_CLIENT_ID") || !env("TOKEN_KEY")) return bad(503, "Google Calendar isn't set up on the board server yet.")
      const d = await req.json().catch(() => ({}))
      const nonce = rand(24)
      await put(`gstate/${nonce}`, { gid, by: me.name, tz: clean(d.tz, 60) || "UTC", at: Date.now() })
      const q = new URLSearchParams({ client_id: env("GOOGLE_CLIENT_ID"), redirect_uri: redirectUri(req), response_type: "code",
                                      scope: G_SCOPES, access_type: "offline", prompt: "consent", include_granted_scopes: "true", state: nonce })
      return json(200, { url: "https://accounts.google.com/o/oauth2/v2/auth?" + q })
    }
    if (method === "POST" && path[1] === "disconnect") {
      if (!me.admin) return bad(403, "Only the group's admin can disconnect it.")
      const gg = await get(`g/${gid}/google`)
      if (gg?.refresh) {
        try { await fetch("https://oauth2.googleapis.com/revoke?token=" + encodeURIComponent(await unseal(gg.refresh)), { method: "POST" }) } catch { /* forget it anyway */ }
      }
      await db().delete(`g/${gid}/google`)
      return json(200, { ok: true })
    }
    if (method === "POST" && path[1] === "busy") {
      const d = await req.json().catch(() => ({}))
      const a = await gAccess(gid)
      if (!a) return json(200, { connected: false, busy: {}, unseen: [] })
      const from = /^\d{4}-\d{2}-\d{2}$/.test(String(d.from)) ? String(d.from) : new Date().toISOString().slice(0, 10)
      const to = /^\d{4}-\d{2}-\d{2}$/.test(String(d.to)) ? String(d.to) : from
      const who: Json[] = []
      for (const m of await members(gid)) {
        const av = await get(`g/${gid}/av/${m.id}`)
        if (av?.email) who.push({ id: m.id, name: m.name, email: av.email })
      }
      if (!who.length) return json(200, { connected: true, busy: {}, unseen: [] })
      const tmin = new Date(from + "T00:00:00Z"); tmin.setUTCDate(tmin.getUTCDate() - 1)
      const tmax = new Date(to + "T00:00:00Z"); tmax.setUTCDate(tmax.getUTCDate() + 2)
      const r = await gFetch(a.token, "https://www.googleapis.com/calendar/v3/freeBusy", { method: "POST",
        body: JSON.stringify({ timeMin: tmin.toISOString(), timeMax: tmax.toISOString(), items: who.map((w) => ({ id: w.email })) }) })
      if (!r.ok) return json(200, { connected: true, busy: {}, unseen: who.map((w) => w.name), error: `Google said ${r.status}` })
      const busy: Record<string, number[][] | (string | number)[][]> = {}, unseen: string[] = []
      const tz = a.g.tz || "UTC"
      for (const w of who) {
        const c = r.body.calendars?.[w.email]
        if (!c || c.errors?.length) { unseen.push(w.name); continue }
        const out: (string | number)[][] = []
        for (const b of c.busy || []) {
          let s = localParts(new Date(b.start), tz)
          const e = localParts(new Date(b.end), tz)
          while (s.date < e.date) {                                   // split across midnights
            out.push([s.date, s.min, 24 * 60])
            const nd = new Date(s.date + "T00:00:00Z"); nd.setUTCDate(nd.getUTCDate() + 1)
            s = { date: nd.toISOString().slice(0, 10), min: 0 }
          }
          if (e.min > s.min) out.push([s.date, s.min, e.min])
        }
        busy[w.id] = out
      }
      return json(200, { connected: true, busy, unseen })
    }
    return bad(404, "No such thing.")
  }

  // -- the band scheduler: availability (each member writes their own) ----------------
  if (method === "GET" && path[0] === "avail") {
    const out: Json[] = []
    for (const m of await members(gid)) {
      const a = (await get(`g/${gid}/av/${m.id}`)) || {}
      out.push({ id: m.id, name: m.name, weekly: a.weekly || [], blackouts: a.blackouts || [], updated: a.updated || 0,
                 email: m.id === mid ? a.email || "" : "", google: !!a.email })
    }
    return json(200, { members: out, me: mid })
  }
  if (method === "POST" && path[0] === "avail") {
    const d = await req.json().catch(() => ({}))
    const hm = (x: unknown) => /^([01]\d|2[0-3]):[0-5]\d$|^24:00$/.test(String(x)) ? String(x) : null
    const ymd = (x: unknown) => /^\d{4}-\d{2}-\d{2}$/.test(String(x)) ? String(x) : null
    const weekly = (Array.isArray(d.weekly) ? d.weekly : []).slice(0, 40).map((w: Json) => ({
      day: Number(w.day), start: hm(w.start), end: hm(w.end) }))
      .filter((w: Json) => w.day >= 0 && w.day <= 6 && w.start && w.end && w.start < w.end)
    const blackouts = (Array.isArray(d.blackouts) ? d.blackouts : []).slice(0, 200).map((b: Json) => ({
      from: ymd(b.from), to: ymd(b.to) || ymd(b.from), note: clean(b.note, 80) }))
      .filter((b: Json) => b.from && b.to && b.from <= b.to)
    const email = /^[^@\s]{1,64}@[^@\s]{1,190}\.[a-z]{2,}$/i.test(String(d.email || "").trim()) ? String(d.email).trim().toLowerCase() : ""
    await put(`g/${gid}/av/${mid}`, { weekly, blackouts, email, updated: Date.now() })
    return json(200, { weekly, blackouts, email })
  }

  // -- the band calendar ---------------------------------------------------------------
  if (method === "GET" && path[0] === "events") {
    const out: Json[] = []
    for (const k of await keys(`g/${gid}/ev/`)) {
      const e = await get(k)
      if (e) out.push({ id: k.split("/").pop(), ...e })
    }
    return json(200, { events: out.sort((a, b) => (a.date + a.start).localeCompare(b.date + b.start)) })
  }
  if (method === "POST" && path[0] === "events") {
    const d = await req.json().catch(() => ({}))
    const kind = ["practice", "show", "other"].includes(d.kind) ? d.kind : "other"
    const date = /^\d{4}-\d{2}-\d{2}$/.test(String(d.date)) ? String(d.date) : ""
    const hm = (x: unknown) => /^([01]\d|2[0-3]):[0-5]\d$|^24:00$/.test(String(x)) ? String(x) : ""
    const start = hm(d.start), end = hm(d.end)
    if (!date || !start) return bad(400, "Give it a date and a start time.")
    if (end && end <= start) return bad(400, "It has to end after it starts.")
    const eid = path[1] ? path[1].replace(/[^a-z0-9]/g, "") : ts() + rand(4)
    const old = path[1] ? await get(`g/${gid}/ev/${eid}`) : null
    if (path[1] && !old) return bad(404, "That event is gone.")
    if (old && old.by_id !== mid && !me.admin) return bad(403, "Only whoever booked it (or the admin) can change it.")
    const label = { practice: "Practice", show: "Show", other: "Event" }[kind as "practice"]
    const ev = { kind, title: clean(d.title, 120) || label, date, start, end, address: clean(d.address, 200), notes: clean(d.notes, 2000),
                 by: old ? old.by : me.name, by_id: old ? old.by_id : mid, created: old ? old.created : Date.now(),
                 updated: Date.now(), cancelled: !!d.cancelled }
    await put(`g/${gid}/ev/${eid}`, { ...ev, gcal_id: old?.gcal_id || "" })
    const synced = await gEventSync(gid, eid, { ...ev, gcal_id: old?.gcal_id || "" }).catch((e) => ({ ...ev, gcal_error: String(e).slice(0, 200) }))
    const [hh, mm] = start.split(":").map(Number)
    const when = new Date(date + "T12:00:00Z").toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric", timeZone: "UTC" })
      + ", " + ((hh % 12) || 12) + (mm ? ":" + String(mm).padStart(2, "0") : "") + (hh < 12 ? " AM" : " PM")
    const what = `${ev.title} ${d.cancelled ? "cancelled" : old ? "changed" : "booked"}: ${when}`
    const at = Date.now()
    await put(`g/${gid}/a/${ts(at)}-${eid}`, { tid: "", eid, title: what, by: me.name, by_id: mid, at, kind: "event" })
    alert(context, g.ntfy, g.name, what, ev.address ? `${ev.address}` : "")
    return json(path[1] ? 200 : 201, { id: eid, ...synced })
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
