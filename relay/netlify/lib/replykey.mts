// The key that lets a Feedback Shooter sender answer on their own issue through /reply, and nobody else.
// It is an HMAC of the repo and issue number. REPLY_SECRET (Netlify env, Functions scope) is used when set;
// otherwise the GitHub token itself is the HMAC key (it never leaves the relay either way). Changing the
// secret or the token makes older keys stop working: those senders answer by signing in to GitHub instead.
import { createHmac, timingSafeEqual } from "node:crypto"

export function replyKey(secret: string, repo: string, number: number): string {
  return createHmac("sha256", secret).update(`philibert-reply:${repo}#${number}`).digest("hex").slice(0, 40)
}

export function keyMatches(secret: string, repo: string, number: number, key: unknown): boolean {
  const want = Buffer.from(replyKey(secret, repo, number))
  const got = Buffer.from(String(key ?? ""))
  return got.length === want.length && timingSafeEqual(got, want)
}
