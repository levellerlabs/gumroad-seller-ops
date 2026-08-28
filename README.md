# gumroad-seller-ops

A [RailCall](https://railcall.ai) marketplace module that puts your entire Gumroad seller loop behind governed, receipted automation: catalogue reads, sales and revenue reporting, license verification, subscriber and audience-email pulls, offer-code create/list/delete, and price updates.

Every command runs through RailCall's airlock: preview, approve, execute, signed receipt. Nothing touches your Gumroad account until you approve it, and every run leaves tamper-evident proof.

Contest entry: `contest:2026Q3` — [marketplace listing](https://railcall.ai/marketplace/levellerco/gumroad-seller-ops).

## Who it's for

Digital-product sellers (ebooks, courses, printables, software) who check Gumroad daily but want those checks inside an auditable workflow instead of raw API calls or repeated dashboard logins. Typical users: a solo creator running a morning sales report; a small shop automating discount launches with an approval step; a virtual assistant granted preview-but-not-execute rights on price changes.

## The 10 commands

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

## Install

```bash
railcall market install levellerco/gumroad-seller-ops
```

Then save one vault entry:

```bash
railcall vault set gumroad '{"access_token":"<your 40-char Gumroad API token>"}'
```

The token is read from the RailCall vault at execution time — never from environment variables, never logged, never included in receipts or error messages.

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

One Gumroad API token (Bearer), stored only in the RailCall vault. Get it from Gumroad Settings → Advanced → Applications. Read commands work with any valid token; write commands exercise exactly the abilities shown above — no other permissions are requested or used.

## Known limitations

- Gumroad's `/sales` endpoint returns one page per call; for shops with thousands of sales, pass `after`/`before` windows.
- `price` updates use Gumroad's integer minor-units field (2900 = £29.00).
- License verification returns 404 mapped to `valid: false` with the server message — a wrong key is an answer, not an error.
- Not affiliated with or endorsed by Gumroad.
