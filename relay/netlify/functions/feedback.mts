// Philibert's feedback relay: a Feedback Shooter message from someone without a GitHub
// account becomes an issue on the Philibert repo, opened with the maker's token.
//
//   POST /send  {kind, part, title, message, system?, version?, website?}
//     -> 201 {number, url}  |  4xx/5xx {error}
//
// Secrets (Netlify env, Functions scope): GITHUB_TOKEN - a fine-grained token with
// Issues: read and write on the Philibert repo only. GITHUB_REPO is optional
// (default below). Nothing is stored here; the issue is the only record.
import type { Config, Context } from "@netlify/functions"

const DEFAULT_REPO = "sskrobe/philibert-esteef-ai"
const KINDS: Record<string, string> = { idea: "Idea", bug: "Something's wrong", change: "Change request", praise: "Praise" }
const PARTS = ["Chat", "Desktop", "App Store", "Notes", "Files", "Models", "Image Generation", "Retro Vault",
  "Band Manager", "Setup / Update", "Something else"]

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } })

const clean = (s: unknown, max: number) => String(s ?? "").replace(/\r\n?/g, "\n").trim().slice(0, max)

export default async (req: Request, context: Context) => {
  if (req.method === "GET") return json(200, { ok: true, service: "philibert-feedback-relay" })
  if (req.method !== "POST") return json(405, { error: "POST only" })

  let d: Record<string, unknown>
  try {
    d = await req.json()
  } catch {
    return json(400, { error: "Send JSON." })
  }
  // A field people never see in Philibert: anything that fills it in is a bot.
  if (d.website) return json(201, { number: 0, url: "" })

  const kind = KINDS[String(d.kind)] ? String(d.kind) : "idea"
  const part = PARTS.includes(String(d.part)) ? String(d.part) : "Something else"
  const title = clean(d.title, 100).replace(/\s+/g, " ")
  const message = clean(d.message, 8000)
  if (title.length < 3 || message.length < 3) return json(400, { error: "Give it a short title and say what you'd like." })

  const lines = [`**Kind:** ${KINDS[kind]}  \n**Part of Philibert:** ${part}`, "", message, ""]
  const sys = d.system && typeof d.system === "object" ? (d.system as Record<string, unknown>) : null
  if (sys) {
    lines.push("<details><summary>Computer details</summary>", "")
    for (const [k, v] of Object.entries(sys).slice(0, 12)) lines.push(`- ${clean(k, 40)}: ${clean(v, 120)}`)
    lines.push("", "</details>", "")
  }
  lines.push("_Sent with Philibert's Feedback Shooter, through the feedback relay (no GitHub account)._")

  const token = Netlify.env.get("GITHUB_TOKEN")
  if (!token) return json(503, { error: "The feedback relay is not set up yet (no GitHub token)." })
  const repo = Netlify.env.get("GITHUB_REPO") || DEFAULT_REPO

  const res = await fetch(`https://api.github.com/repos/${repo}/issues`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: "application/vnd.github+json",
      "User-Agent": "philibert-feedback-relay",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ title: `[${KINDS[kind]}] ${title}`.slice(0, 120), body: lines.join("\n"), labels: ["feedback"] }),
  })
  if (!res.ok) {
    console.log("GitHub said", res.status, (await res.text()).slice(0, 300))
    return json(502, { error: `GitHub did not take it (${res.status}). Try again later.` })
  }
  const issue = await res.json()
  return json(201, { number: issue.number, url: issue.html_url })
}

export const config: Config = {
  path: "/send",
  method: ["GET", "POST"],
  // A person sends a few messages; a script sends hundreds.
  rateLimit: { windowLimit: 5, windowSize: 60, aggregateBy: ["ip", "domain"] },
}
