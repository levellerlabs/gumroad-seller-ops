# gumroad-seller-ops

A [RailCall](https://railcall.ai) marketplace module that puts your entire Gumroad seller loop behind governed, receipted automation: catalogue reads, sales and revenue reporting, license verification, subscriber and audience-email pulls, offer-code create/list/delete, and price updates.

Every command runs through RailCall's airlock: preview, approve, execute, signed receipt. Nothing touches your Gumroad account until you approve it, and every run leaves tamper-evident proof.

Contest entry: `contest:round2` - [marketplace listing](https://railcall.ai/marketplace/levellerco/gumroad-seller-ops) (v1.0.3, in review).

## Who it's for

Digital-product sellers (ebooks, courses, printables, software) who check Gumroad daily but want those checks inside an auditable workflow instead of raw API calls or repeated dashboard logins. Typical users: a solo creator running a morning sales report; a small shop automating discount launches with an approval step; a virtual assistant granted preview-but-not-execute rights on price changes.

## The 11 commands

| Command | Mode | What it does |
|---|---|---|
| `gumroad.list_products` | read | Catalogue with price, sales count, publish state |
| `gumroad.get_product` | read | One product's live state |
| `gumroad.sales_summary` | read | Refund-aware gross/net revenue totals for a date range |
| `gumroad.list_sales` | read | Detail rows: product, buyer email, price, refund flags |
| `gumroad.verify_license` | read | License check mapped to a clean valid/invalid answer |
| `gumroad.list_subscribers` | read | Subscribers incl. cancellation state |
| `gumroad.list_emails` | read | Audience email list with purchase linkage |
| `gumroad.create_offer_code` | write | Percent or fixed discount, optional usage cap |
| `gumroad.list_offer_codes` | read | Active codes with times_used |
| `gumroad.delete_offer_code` | write | Retire a code |
| `gumroad.update_price` | write | Price change in integer pence/cents |

Writes are `write_requires_approval` with `side_effects: external`; the airlock forces a human approval before execution and a signed receipt after.

## Demo video

[`demo.mp4`](demo.mp4) (2 min 17 s, 1280x800, H.264) shows the module live in RailCall Studio v1.5.8 against the real Gumroad API - no mocks:

1. the marketplace listing and the installed module, v1.0.3, signature verified
2. the Sends airlock with all 11 commands registered
3. a read (`gumroad.get_product`): preview -> pending approval -> approve -> execute -> HTTP 200, receipt signed
4. a real write (`gumroad.create_offer_code`, 10% `RCMOD-DEMO`): same ceremony, code goes live on Gumroad
5. cleanup (`gumroad.delete_offer_code`): the demo code is deleted through the airlock - net side effects zero
6. the receipts ledger: every run listed with signer and a verifiable signature

## Repo layout = the signed module tree

This repository mirrors the module exactly as published to the marketplace (v1.0.3, manifest v2 tree signature):

```
module.json            # manifest (11 commands, credential spec, pinned network)
handlers/handler.py    # the handler that executes every command
description.txt        # the marketplace listing copy
module.sig             # Ed25519 signature over canonical(module.json) || tree manifest
```

`module.sig` is the publisher signature over the deterministic tree manifest (`relpath<TAB>sha256` lines). The signed tree is `module.json` + `handlers/handler.py` + `description.txt`; `README.md` and `LICENSE` are repo-only. Verify after cloning:

```bash
python3 - <<'PY'
import json, hashlib, os, fnmatch
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

m = json.load(open("module.json"))
ignore = ("__pycache__/", "*.pyc", "*.pyo", "*.pyd", ".pytest_cache/", ".mypy_cache/",
          ".ruff_cache/", ".git/", ".gitignore", ".env", ".env.*", "*.env", ".railcall/",
          ".railcall_workspace/", "node_modules/", "*.log", ".DS_Store", "module.sig",
          "publisher.attestation.json",
          "README.md", "LICENSE")  # repo-only files, not part of the signed tree

def ignored(rel):
    import fnmatch
    parts = rel.split("/")
    for pat in ignore:
        if pat.endswith("/"):
            if pat[:-1] in parts:
                return True
        elif fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(parts[-1], pat):
            return True
    return False

files = []
for dirpath, _, filenames in os.walk("."):
    for fn in filenames:
        rel = os.path.relpath(os.path.join(dirpath, fn), ".").replace("\\", "/")
        if ignored(rel):
            continue
        files.append((rel, hashlib.sha256(open(rel, "rb").read()).hexdigest()))
files.sort()
tree = "".join(f"{r}\t{s}\n" for r, s in files).encode()
canonical = json.dumps({k: v for k, v in m.items() if k != "signature"},
                       sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
Ed25519PublicKey.from_public_bytes(bytes.fromhex(m["publisher_pubkey"])).verify(
    bytes.fromhex(open("module.sig").read().strip()), canonical + b"\n" + tree)
print("signature OK - tree matches the marketplace listing")
PY
```

## Install

```bash
railcall market install levellerco/gumroad-seller-ops
```

Then save one vault entry:

```bash
railcall vault set gumroad '{"access_token":"<your 40-char Gumroad API token>"}'
```

The token is read from the RailCall vault at execution time - never from environment variables, never logged, never included in receipts or error messages.

## Worked example: morning revenue check

```
you:    gumroad.sales_summary after=2026-08-01
preview: 7 sales, gross 20300p, net 19015p, currency GBP  [approve?]
you:    approve
receipt: executed, signed, refund-aware totals on record
```

## Worked example: launch a 20% weekend code

```
you:    gumroad.create_offer_code product_id=2Fo8dBo4... name=AUG20 amount_off=20 offer_type=percent max_purchase_count=50
preview: will POST percent code AUG20 (cap 50)  [approve?]
you:    approve
receipt: offer_code_id returned, signed
```

## Credentials

One Gumroad API token (Bearer), stored only in the RailCall vault. Get it from Gumroad Settings -> Advanced -> Applications. Read commands work with any valid token; write commands exercise exactly the abilities shown above - no other permissions are requested or used.

## Known limitations

- Gumroad's `/sales` endpoint returns one page per call; for shops with thousands of sales, pass `after`/`before` windows.
- `price` updates use Gumroad's integer minor-units field (2900 = £29.00).
- License verification returns 404 mapped to `valid: false` with the server message - a wrong key is an answer, not an error.
- Not affiliated with or endorsed by Gumroad.
