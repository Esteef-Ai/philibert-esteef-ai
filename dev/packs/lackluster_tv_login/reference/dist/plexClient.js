import { config } from './config.js';
function plexHeaders(extra = {}) {
    return {
        Accept: 'application/json',
        'X-Plex-Product': config.plexProduct,
        'X-Plex-Version': '1.0',
        'X-Plex-Client-Identifier': config.plexClientIdentifier,
        'X-Plex-Model': 'Plex OAuth',
        ...extra,
    };
}
/**
 * Step 1 of the "Sign in with Plex" flow: ask plex.tv for a fresh PIN.
 * The viewer is sent to the returned auth URL (in a new tab/window) to log
 * in with their own Plex account. We poll `pollPin` afterward until Plex
 * reports back an auth token for this PIN.
 */
export async function createPin(opts = {}) {
    const strong = opts.strong !== false;
    const res = await fetch(`${config.plexTvUrl}/api/v2/pins` + (strong ? '?strong=true' : ''), {
        method: 'POST',
        headers: plexHeaders(),
    });
    if (!res.ok) {
        throw new Error(`Plex pin creation failed: ${res.status}`);
    }
    const pin = (await res.json());
    let authUrl = `${config.plexAuthAppUrl}#!?clientID=${config.plexClientIdentifier}` +
        `&code=${pin.code}` +
        `&context[device][product]=${encodeURIComponent(config.plexProduct)}`;
    if (opts.forwardUrl) {
        authUrl += `&forwardUrl=${encodeURIComponent(opts.forwardUrl)}`;
    }
    return { pin, authUrl };
}
export async function pollPin(pinId) {
    const res = await fetch(`${config.plexTvUrl}/api/v2/pins/${pinId}`, {
        headers: plexHeaders(),
    });
    if (res.status === 404) {
        return { status: 'expired' };
    }
    if (!res.ok) {
        throw new Error(`Plex pin poll failed: ${res.status}`);
    }
    const body = (await res.json());
    if (body.authToken) {
        return { status: 'ok', authToken: body.authToken };
    }
    return { status: 'pending' };
}
export async function getPlexUser(authToken) {
    const res = await fetch(`${config.plexTvUrl}/api/v2/user`, {
        headers: plexHeaders({ 'X-Plex-Token': authToken }),
    });
    if (!res.ok) {
        throw new Error(`Failed to fetch Plex user: ${res.status}`);
    }
    return (await res.json());
}
/**
 * The source of truth for "is this Plex account allowed in": try the
 * token directly against OUR Plex server. Plex itself only accepts tokens
 * that belong to the server owner or an account the owner has explicitly
 * shared the server with — so a 200 here means "yes, this person is
 * already one of your Plex users," with no separate friends-list parsing
 * required (same approach tools like Overseerr use).
 */
export async function checkServerAccess(authToken) {
    try {
        const res = await fetch(`${config.plexServerUrl}/identity`, {
            headers: { Accept: 'application/json', 'X-Plex-Token': authToken },
            signal: AbortSignal.timeout(8000),
        });
        return res.ok;
    }
    catch {
        return false;
    }
}
/**
 * Convenience helper for the channel-tag editor: list genre values Plex
 * already knows about for a given library section, so the admin can pick
 * from real tags instead of typing them freehand.
 */
export async function listSectionGenres(adminToken, sectionId) {
    const res = await fetch(`${config.plexServerUrl}/library/sections/${sectionId}/genre`, { headers: { Accept: 'application/json', 'X-Plex-Token': adminToken } });
    if (!res.ok)
        return [];
    const body = (await res.json());
    return (body.MediaContainer?.Directory ?? []).map((d) => d.title);
}
//# sourceMappingURL=plexClient.js.map