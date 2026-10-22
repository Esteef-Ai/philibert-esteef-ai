r"""Mirror the third-party GGUF models Philibert offers onto the Esteef.Ai
Hugging Face organisation, so installs never depend on someone else keeping
their repository up. Each mirror is the original file, unmodified (its SHA-256
is checked against the original repository first), with a model card that names
the original author, links the original and keeps its licence.

    python dev/hf_mirror.py            dry run: checks everything, uploads nothing
    python dev/hf_mirror.py --go       creates the repos (public) and uploads (resumable)

The files come from the local Ollama store; they are staged as hard links (no
copies) under <store>/_hf_upload and uploaded with upload_large_folder, which
picks up where it stopped if the connection drops.
"""
import hashlib
import json
import os
import sys
from pathlib import Path

ORG = "EsteefAi"
STORE = Path(os.environ.get("OLLAMA_MODELS") or r"G:\AI_Chat_Models")
STOPS = ["<|im_start|>", "<|im_end|>", "<think>", "<|im_start|>user"]

MIRRORS = [
    {"repo": "Qwen3.8-27B-ZB-IQ4_XS-GGUF-mirror", "source": "tooltd/Qwen3.8-27B-IQ4-XS-16GB-VRAM-GGUF",
     "author": "tooltd", "license": "apache-2.0", "base": "Qwen/Qwen3.8-27B",
     "title": "Qwen3.8 27B ZB (IQ4_XS) - mirror",
     "files": {"Qwen3.8-27B-ZB4.00-MIN-v5.1-IQ4_XS.gguf": "2be449820b8f8e2e97fb0fe668914e064af523eeca8337bf07b397e1945f8e81"},
     "ollama": ["ZB4.00-MIN-v5.1-IQ4_XS"]},
    {"repo": "Qwen3.8-27B-Defiance-Uncensored-MTP-GGUF-mirror", "source": "ttindall/Qwen3.8-27B-Defiance-Uncensored-MTP-GGUF",
     "author": "ttindall", "license": "apache-2.0",
     "base": ["HauhauCS/Qwen3.8-27B-Uncensored-HauhauCS-Aggressive-MTP-GGUF",
              "DavidAU/Qwen3.8-27B-Turbo-Brilliance-50X-Reasoning-Instruct-NEO-MAX-MTP-GGUF"],
     "title": "Qwen3.8 27B Defiance Uncensored (IQ4_XS, Q6_K_P) - mirror",
     "files": {"Qwen3.8-27B-Defiance-Uncensored-IQ4_XS.gguf": "d48cdb6e627b4e74b862938daf5ac2bfb7b82c5f02627a02a3b4927e7bb35f2f",
               "Qwen3.8-27B-Defiance-Uncensored-Q6_K_P.gguf": "0ce1abf7e488a5efbd4408af763f18e21bdc220c93106f658d95607dc97868a3"},
     "ollama": ["IQ4_XS", "Q6_K_P"]},
]


def card(m):
    base = m["base"] if isinstance(m["base"], list) else [m["base"]]
    rows = "\n".join(f"| `{f}` | `{h}` |" for f, h in m["files"].items())
    pulls = "\n".join(f"    ollama pull hf.co/{ORG}/{m['repo']}:{t}" for t in m["ollama"])
    return f"""---
license: {m['license']}
base_model:
{chr(10).join('- ' + b for b in base)}
tags:
- gguf
- mirror
---

# {m['title']}

**This is a mirror, not our work.** It is an unmodified copy of
[{m['source']}](https://huggingface.co/{m['source']}) by
[{m['author']}](https://huggingface.co/{m['author']}), kept here so that
[Philibert](https://huggingface.co/{ORG}) installs keep working even if the
original moves. All credit belongs to the original author and to the authors of
the base model(s). Please see, follow and cite the original repository.

- **Original:** https://huggingface.co/{m['source']}
- **Author:** {m['author']}
- **Licence:** {m['license']} (unchanged from the original)
- **Changes:** none - the files are byte-for-byte the originals (SHA-256 below)

| File | SHA-256 (same as the original) |
| --- | --- |
{rows}

## With Ollama

{pulls}

`params` holds the stop words Philibert uses with these files; the chat template is
the one inside each GGUF, as published by the original author.

Mirrored by Esteef.Ai for Philibert. If you are the author and want this mirror
changed or removed, open a discussion on this repository.
"""


def sha256(p, chunk=1 << 24):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                return h.hexdigest()
            h.update(b)


def main(go):
    from huggingface_hub import HfApi
    api = HfApi()
    me = api.whoami()
    print("signed in as", me.get("name"), "| orgs:", [o.get("name") for o in me.get("orgs", [])])
    for m in MIRRORS:
        src = api.model_info(m["source"], files_metadata=True)
        remote = {s.rfilename: (s.lfs.get("sha256") if isinstance(s.lfs, dict) else getattr(s.lfs, "sha256", None))
                  for s in src.siblings}
        stage = STORE / "_hf_upload" / m["repo"]
        stage.mkdir(parents=True, exist_ok=True)
        total = 0
        for fname, digest in m["files"].items():
            blob = STORE / "blobs" / f"sha256-{digest}"
            assert blob.is_file(), f"missing {blob}"
            assert remote.get(fname) == digest, f"{fname}: the original's SHA-256 differs - not a faithful mirror"
            link = stage / fname
            if not link.exists():
                os.link(blob, link)          # a hard link: no second 25 GB copy
            total += blob.stat().st_size
        (stage / "README.md").write_text(card(m), encoding="utf-8")
        (stage / "params").write_text(json.dumps({"stop": STOPS}, indent=1), encoding="utf-8")
        print(f"{ORG}/{m['repo']}: {len(m['files'])} file(s), {total / 1e9:.1f} GB, matches {m['source']} - staged in {stage}")
        if not go:
            continue
        api.create_repo(f"{ORG}/{m['repo']}", repo_type="model", private=False, exist_ok=True)
        api.upload_large_folder(repo_id=f"{ORG}/{m['repo']}", folder_path=str(stage), repo_type="model",
                                allow_patterns=["*.gguf", "README.md", "params"])
        print("uploaded", f"https://huggingface.co/{ORG}/{m['repo']}")
    if not go:
        print("dry run: nothing uploaded. Run with --go to publish.")


if __name__ == "__main__":
    main("--go" in sys.argv)
