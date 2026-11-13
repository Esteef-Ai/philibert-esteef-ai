import { db } from '../db.js';
import { checkServerAccess, createPin, getPlexUser, pollPin, } from '../plexClient.js';
import { clearSessionCookie, createSession, destroySession, readSessionCookie, setSessionCookie, } from './session.js';
const PIN_COOKIE = 'lp_pin';
function rememberPin(reply, pinId) {
    reply.setCookie(PIN_COOKIE, String(pinId), { httpOnly: true, sameSite: 'lax', secure: process.env.NODE_ENV === 'production', path: '/', maxAge: 1800, signed: true });
}
function forgetPin(reply) {
    reply.clearCookie(PIN_COOKIE, { path: '/' });
}
function readPin(req) {
    const raw = req.cookies[PIN_COOKIE];
    if (!raw) return null;
    const got = req.unsignCookie(raw);
    const id = got.valid ? Number(got.value) : 0;
    return id > 0 ? id : null;
}
const ACCESS_CACHE_TTL_MS = 10 * 60 * 1000; // re-verify against Plex every 10 min
async function hasServerAccess(plexUserId, token) {
    const cached = db
        .prepare('SELECT has_access as hasAccess, checked_at as checkedAt FROM access_cache WHERE plex_user_id = ?')
        .get(plexUserId);
    if (cached && Date.now() - cached.checkedAt < ACCESS_CACHE_TTL_MS) {
        return cached.hasAccess === 1;
    }
    const allowed = await checkServerAccess(token);
    db.prepare(`INSERT INTO access_cache (plex_user_id, has_access, checked_at)
     VALUES (?, ?, ?)
     ON CONFLICT(plex_user_id) DO UPDATE SET has_access = excluded.has_access, checked_at = excluded.checked_at`).run(plexUserId, allowed ? 1 : 0, Date.now());
    return allowed;
}
export async function registerAuthRoutes(app) {
    // Step 1: client asks us for a Plex sign-in PIN + URL to send the user to.
    app.post('/auth/plex/start', async (req, reply) => {
        const mode = req.body?.mode;
        if (mode === 'link') {
            const { pin } = await createPin({ strong: false });
            rememberPin(reply, pin.id);
            return reply.send({ mode: 'link', code: pin.code, linkUrl: 'https://plex.tv/link', qrUrl: pin.qr ?? null, expiresIn: pin.expiresIn ?? 900 });
        }
        if (mode === 'redirect') {
            const forwardUrl = `${req.protocol}://${req.host}/?signin=return`;
            const { pin, authUrl } = await createPin({ forwardUrl });
            rememberPin(reply, pin.id);
            return reply.send({ mode: 'redirect', authUrl });
        }
        const { pin, authUrl } = await createPin();
        rememberPin(reply, pin.id);
        return reply.send({ pinId: pin.id, code: pin.code, authUrl });
    });
    // Step 2: client polls this while the user completes sign-in in the
    // Plex tab. Once Plex reports an authToken, we verify the account
    // actually has access to THIS Plex server before creating a session —
    // being logged into Plex.tv is not enough on its own.
    app.get('/auth/plex/poll', async (req, reply) => {
        const pinId = readPin(req);
        if (pinId === null) {
            return reply.status(400).send({ status: 'none', error: 'No sign-in is in progress in this browser.' });
        }
        const pin = await pollPin(pinId);
        if (pin.status === 'pending') {
            return reply.send({ status: 'pending' });
        }
        forgetPin(reply);
        if (pin.status === 'expired') {
            return reply.send({ status: 'expired' });
        }
        const authToken = pin.authToken;
        const plexUser = await getPlexUser(authToken);
        const allowed = await hasServerAccess(String(plexUser.id), authToken);
        if (!allowed) {
            return reply.status(403).send({
                status: 'denied',
                error: 'This Plex account does not have access to the configured ' +
                    'Plex server. Ask the server owner to share the library with ' +
                    'you, then try signing in again.',
            });
        }
        const session = createSession(plexUser, authToken);
        setSessionCookie(reply, session.id);
        return reply.send({
            status: 'ok',
            user: {
                username: session.username,
                thumb: session.thumb,
                role: session.role,
            },
        });
    });
    app.get('/auth/me', async (req, reply) => {
        if (!req.user) {
            return reply.status(401).send({ error: 'not signed in' });
        }
        return reply.send({
            username: req.user.username,
            thumb: req.user.thumb,
            role: req.user.role,
        });
    });
    app.post('/auth/logout', async (req, reply) => {
        const sessionId = readSessionCookie(req);
        if (sessionId)
            destroySession(sessionId);
        clearSessionCookie(reply);
        return reply.send({ status: 'ok' });
    });
    // Browser-friendly logout: just type /auth/logout into the address bar
    // and you're signed out and back at the sign-in screen. Escape hatch for
    // whenever a stale/odd session is suspected -- no UI required.
    app.get('/auth/logout', async (req, reply) => {
        const sessionId = readSessionCookie(req);
        if (sessionId)
            destroySession(sessionId);
        clearSessionCookie(reply);
        return reply.redirect('/', 302);
    });
}
//# sourceMappingURL=routes.js.map
