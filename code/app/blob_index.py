#!/usr/bin/env python3
"""
Make the Ollama blob store readable.

Ollama names every file after its sha256 digest, so `D:\\Models\\blobs`
is a wall of unreadable hashes. This walks the manifests, works out which model
each blob belongs to, and writes a plain-English index next to them.

    python blob_index.py            # print + write _BLOB_INDEX.md
    python blob_index.py --csv      # also write _BLOB_INDEX.csv

NEVER rename the blob files themselves — Ollama looks them up by exact digest
and renaming one makes the model unloadable. This only writes an index beside
them, which is why it is safe to run any time.
"""
import json, os, sys, pathlib, datetime

def find_store():
    """Ollama's model dir is often only recorded in its own server log."""
    env = os.environ.get("OLLAMA_MODELS")
    if env and pathlib.Path(env).exists():
        return pathlib.Path(env)
    log = pathlib.Path(os.environ.get("LOCALAPPDATA", "")) / "Ollama" / "server.log"
    if log.exists():
        try:
            txt = log.read_text(encoding="utf-8", errors="replace")
            i = txt.rfind("OLLAMA_MODELS:")
            if i != -1:
                val = txt[i + 14:].split()[0].strip().replace("\\\\", "\\")
                p = pathlib.Path(val)
                if p.exists():
                    return p
        except Exception:
            pass
    for guess in (pathlib.Path.home() / ".ollama" / "models",
                  pathlib.Path(r"D:\Models")):
        if (guess / "blobs").exists():
            return guess
    return None


# Ollama layer media types, in plain English
KIND = {
    "application/vnd.ollama.image.model":     "WEIGHTS",
    "application/vnd.ollama.image.projector": "vision projector",
    "application/vnd.ollama.image.adapter":   "LoRA adapter",
    "application/vnd.ollama.image.template":  "prompt template",
    "application/vnd.ollama.image.system":    "system prompt",
    "application/vnd.ollama.image.params":    "parameters",
    "application/vnd.ollama.image.license":   "license",
    "application/vnd.docker.container.image.v1+json": "config",
}

def human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:,.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024

def build(store):
    blobs, man = store / "blobs", store / "manifests"
    owners = {}                     # digest-filename -> [(model, kind)]
    for mf in man.rglob("*"):
        if not mf.is_file():
            continue
        try:
            d = json.loads(mf.read_text(encoding="utf-8"))
        except Exception:
            continue
        parts = mf.relative_to(man).parts          # registry/library/name/tag
        model = f"{parts[-2]}:{parts[-1]}" if len(parts) >= 2 else str(mf)
        layers = list(d.get("layers", []))
        if d.get("config"):
            layers.append(d["config"])
        for L in layers:
            fn = (L.get("digest") or "").replace(":", "-")
            owners.setdefault(fn, []).append((model, KIND.get(L.get("mediaType"), L.get("mediaType", "?"))))

    rows = []
    for f in sorted(blobs.iterdir()):
        # Only real blobs. The index files this script writes live here too, and
        # counting them would report them as scary "orphaned" data.
        if not f.is_file() or not f.name.startswith("sha256-"):
            continue
        own = owners.get(f.name, [])
        models = sorted({m for m, _ in own})
        kinds = sorted({k for _, k in own})
        rows.append({
            "file": f.name,
            "short": f.name[:19] + "…",
            "bytes": f.stat().st_size,
            "size": human(f.stat().st_size),
            "models": models,
            "kind": ", ".join(kinds) if kinds else "ORPHAN — not referenced by any model",
            "shared": len(models) > 1,
            "orphan": not models,
        })
    rows.sort(key=lambda r: -r["bytes"])
    return rows

def main():
    store = find_store()
    if not store:
        print("Could not locate the Ollama model store."); sys.exit(1)
    rows = build(store)
    total = sum(r["bytes"] for r in rows)
    orph = [r for r in rows if r["orphan"]]

    out = [f"# Ollama blob index",
           "",
           f"Store: `{store}`  ",
           f"Generated: {datetime.datetime.now():%Y-%m-%d %H:%M}  ",
           f"{len(rows)} blobs, {human(total)} total"]
    if orph:
        out.append(f"  \n**{len(orph)} orphaned blob(s), {human(sum(r['bytes'] for r in orph))} reclaimable "
                   "— run `ollama rm` on nothing; these are safe to delete directly.**")
    out += ["", "| Size | Blob file | Belongs to | Contents |", "|---|---|---|---|"]
    for r in rows:
        who = "<br>".join(r["models"]) if r["models"] else "**ORPHAN**"
        if r["shared"]:
            who += "<br>_(shared — deleting one model frees nothing)_"
        out.append(f"| {r['size']} | `{r['file']}` | {who} | {r['kind']} |")

    # what each model actually costs
    per = {}
    for r in rows:
        for m in r["models"]:
            per.setdefault(m, {"total": 0, "unique": 0})
            per[m]["total"] += r["bytes"]
            if not r["shared"]:
                per[m]["unique"] += r["bytes"]
    out += ["", "## What deleting each model would actually free", "",
            "| Model | Frees | On-disk total |", "|---|---|---|"]
    for m, v in sorted(per.items(), key=lambda kv: -kv[1]["unique"]):
        # Only warn when the shared portion is big enough to matter. Every model
        # shares a few KB of licence/template files; saying "shares data" for
        # that is just noise.
        shared_bytes = v["total"] - v["unique"]
        note = " ⚠ shares its weights with another model" if shared_bytes > 100 * 1024 * 1024 else ""
        out.append(f"| `{m}` | {human(v['unique'])}{note} | {human(v['total'])} |")

    md = store / "blobs" / "_BLOB_INDEX.md"
    md.write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out[:6]))
    print(f"\nWrote {md}")

    if "--csv" in sys.argv:
        import csv
        p = store / "blobs" / "_BLOB_INDEX.csv"
        with open(p, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["blob_file", "bytes", "size", "models", "contents", "shared", "orphan"])
            for r in rows:
                w.writerow([r["file"], r["bytes"], r["size"], "; ".join(r["models"]),
                            r["kind"], r["shared"], r["orphan"]])
        print(f"Wrote {p}")


if __name__ == "__main__":
    main()
