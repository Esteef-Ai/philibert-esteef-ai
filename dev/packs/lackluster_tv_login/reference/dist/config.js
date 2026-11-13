import 'dotenv/config';
import path from 'node:path';
function required(name, fallback) {
    const v = process.env[name] ?? fallback;
    if (!v) {
        throw new Error(`Missing required environment variable: ${name}`);
    }
    return v;
}
export const config = {
    externalPort: Number(process.env.EXTERNAL_PORT ?? 9191),
    tunarrInternalUrl: required('TUNARR_INTERNAL_URL', 'http://tunarr:8000'),
    plexServerUrl: required('PLEX_SERVER_URL'),
    adminPlexUsernames: (process.env.ADMIN_PLEX_USERNAMES ?? '')
        .split(',')
        .map((s) => s.trim().toLowerCase())
        .filter(Boolean),
    sessionSecret: required('SESSION_SECRET'),
    dataDir: process.env.DATA_DIR ?? './data',
    // Lackluster Plus+ patch: "Re-Skin" -- optional decorative TV-frame
    // overlays for Media view. Each subfolder here is one skin, containing a
    // "screen.<ext>" (the frame, with its screen area already cut fully
    // transparent by whoever made it -- video shows through the hole when
    // layered on top) and optionally a "panel.<ext>" (a texture for the
    // docked chat/draw panel). Defaults to a sibling of wherever the Gateway
    // process actually runs from (C:\LacklusterPlus\images\Borders in a
    // normal install), same convention as dataDir above.
    bordersDir: process.env.BORDERS_DIR ?? path.join(process.cwd(), '..', 'images', 'Borders'),
    // Lackluster Plus+ patch: audio clip export -- the Gateway spawns ffmpeg
    // itself (separately from Tunarr's own transcoding) to cut a start/end
    // range out of whatever's currently airing on a channel and hand back an
    // audio file. Defaults to assuming ffmpeg is on PATH; override with the
    // exact .exe path (e.g. C:\ffmpeg\bin\ffmpeg.exe, the same install
    // Tunarr's own ffmpeg-error logs reference) if it isn't.
    ffmpegPath: process.env.FFMPEG_PATH ?? 'ffmpeg',
    // Identifies this app to Plex's API. A stable random-looking string is
    // fine — Plex just uses it to group "this app"'s auth requests together
    // in the user's Plex account under Settings > Devices.
    plexClientIdentifier: process.env.PLEX_CLIENT_IDENTIFIER ??
        'lackluster-plus-gateway-9f3c1a',
    plexProduct: 'Lackluster Plus+',
    // Where Plex's sign-in services live. Only ever changed by the tests,
    // which point both at a local stand-in so no test talks to the real Plex.
    plexTvUrl: (process.env.PLEX_TV_URL ?? 'https://plex.tv').replace(/\/+$/, ''),
    plexAuthAppUrl: process.env.PLEX_AUTH_APP_URL ?? 'https://app.plex.tv/auth/',
};
if (config.adminPlexUsernames.length === 0) {
    // eslint-disable-next-line no-console
    console.warn('[config] ADMIN_PLEX_USERNAMES is empty — nobody will get the Admin ' +
        'role until this is set in your .env file.');
}
//# sourceMappingURL=config.js.map