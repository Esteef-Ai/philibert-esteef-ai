// Philibert's feedback relay: the sender of a Feedback Shooter message answers the maker on its issue.
//
//   POST /reply  {number, key, message, website?}
//     -> 201 {id}  |  4xx/5xx {error}
//
// key is what /send handed back for that issue (netlify/lib/replykey.mts), so only the person who sent the
// message can answer on it through here. Only issues labelled "feedback" take answers. Nothing is stored here.
import type { Config, Context } from "@netlify/functions"
import { keyMatches } from "../lib/replykey.mts"

const DEFAULT_REPO = "Esteef-Ai/philibert-esteef-ai"

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } })

export default async (req: Request, context: Context) => {
  if (req.method !== "POST") return json(405, { error: "POST only" })
  let d: Record<string, unknown>
  try {
    d = await req.json()
  } catch {
    return json(400, { error: "Send JSON." })
  }
  if (d.website) return json(201, { id: 0 })        // the bot trap, as in /send

  const token = Netlify.env.get("GITHUB_TOKEN")
  if (!token) return json(503, { error: "The feedback relay is not set up yet (no GitHub token)." })
  const repo = Netlify.env.get("GITHUB_REPO") || DEFAULT_REPO
  const number = Number(d.number)
  if (!Number.isInteger(number) || number < 1) return json(400, { error: "Which message is this an answer to?" })
  if (!keyMatches(Netlify.env.get("REPLY_SECRET") || token, repo, number, d.key))
    return json(403, { error: "This message can't be answered from here any more. Sign in to GitHub to answer it, or send a new message." })
  const message = String(d.message ?? "").replace(/\r\n?/g, "\n").trim().slice(0, 4000)
  if (message.length < 2) return json(400, { error: "Write your answer first." })

  const gh = (path: string, init: RequestInit = {}) => fetch(`https://api.github.com/repos/${repo}${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: "application/vnd.github+json",
      "User-Agent": "philibert-feedback-relay",
      "Content-Type": "application/json",
    },
  })
  const issue = await gh(`/issues/${number}`)
  if (!issue.ok) return json(502, { error: `GitHub did not answer (${issue.status}). Try again later.` })
  const it = await issue.json()
  if (!(it.labels || []).some((l: { name?: string }) => l.name === "feedback"))
    return json(403, { error: "That is not a Feedback Shooter message." })

  const body = `**The sender answered** (from Philibert, through the feedback relay):\n\n${message}`
  const res = await gh(`/issues/${number}/comments`, { method: "POST", body: JSON.stringify({ body }) })
  if (!res.ok) {
    console.log("GitHub said", res.status, (await res.text()).slice(0, 300))
    return json(502, { error: `GitHub did not take it (${res.status}). Try again later.` })
  }
  const c = await res.json()
  return json(201, { id: c.id })
}

export const config: Config = {
  path: "/reply",
  method: ["POST"],
  rateLimit: { windowLimit: 5, windowSize: 60, aggregateBy: ["ip", "domain"] },
}
