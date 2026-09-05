"""levellerco/gumroad-seller-ops v1.0.0 — governed Gumroad seller operations.

Vault entry `gumroad`:
    { "access_token": "<40-char Gumroad API token>" }

All commands hit https://api.gumroad.com/v2 with `Authorization: Bearer <token>`.
One vault entry covers every command.

Shapes verified against the live v2 API (2026-08-25):
  - GET  /products                       -> {"products": [...]}
  - GET  /products/{id}                  -> {"product": {...}}
  - GET  /sales?product_id=<urlencoded>  -> {"sales": [...]}   (global /sales with optional filters)
  - POST /licenses/verify                -> 200 valid | 404 {"success": false, "message": ...}
  - GET  /products/{id}/subscribers      -> {"subscribers": [...]}
  - GET  /emails                         -> {"emails": [...]}
  - POST /products/{id}/offer_codes      body: name, amount_off, offer_type=percent|fixed (default fixed)
  - GET  /products/{id}/offer_codes      -> {"offer_codes": [...]}
  - DELETE /products/{id}/offer_codes/{oc_id}
  - PUT  /products/{id}                  body: price (integer cents/pence)

Notes:
  - Product IDs contain '=' and '/' (e.g. "2Fo8dBo4Wz5iVRpK0mbPlQ=="); every
    path segment is URL-quoted so the request line stays valid.
  - /licenses/verify returns 404 for a nonexistent license — mapped here to
    {"valid": false, ...} with the server message, not an exception, because
    "this key is not valid" is a normal answer, not an operational failure.
  - offer percent codes: send offer_type=percent and amount_off=<int percent>.
    Fixed codes omit offer_type (server default) and amount_off=<major units>.
  - Errors are raised with clear messages (the airlock records them); secrets
    are never included in results or exceptions.
"""

BASE = "https://api.gumroad.com/v2"


def _load_bearer():
    helpers = __rc_helpers__  # noqa: F821
    vault_get = helpers["vault_get"]
    entry = vault_get("gumroad")
    if not isinstance(entry, dict):
        raise RuntimeError("no Gumroad credential saved — configure the `gumroad` vault entry with access_token")
    bearer = str(entry.get("access_token") or "").strip()
    if not bearer:
        raise RuntimeError("Gumroad credential missing access_token")
    return bearer


def _req(method, path, form=None):
    """One Gumroad call. Returns (http_status, parsed_json_or_none).

    Uses urllib from the handler namespace so the module's network gate
    (requires.network = ["api.gumroad.com"]) governs every request.
    Raises RuntimeError on network/parse failure with a clear message.
    """
    helpers = __rc_helpers__  # noqa: F821
    import urllib.request as _ur
    import urllib.parse as _up
    import urllib.error as _ue
    import json as _json

    url = BASE + path
    data = None
    if form is not None:
        data = _up.urlencode(form).encode("utf-8")
    req = _ur.Request(url, data=data, method=method)
    req.add_header("Authorization", "Bearer " + _load_bearer())
    if data is not None:
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with _ur.urlopen(req, timeout=30) as r:
            raw = r.read().decode("utf-8")
            return r.getcode(), (_json.loads(raw) if raw.strip() else None)
    except _ue.HTTPError as e:
        try:
            detail = e.read().decode("utf-8")
            parsed = _json.loads(detail) if detail.strip() else None
        except Exception:
            parsed = None
        return e.code, parsed
    except Exception as e:  # network layer refused (sandbox gate or outage)
        raise RuntimeError("Gumroad request failed (%s %s): %s" % (method, path, str(e)[:160]))


def _q(path, params):
    """Append URL-encoded query params, dropping empties. Values URL-encoded once."""
    import urllib.parse as _up
    clean = {str(k): str(v) for k, v in (params or {}).items() if v not in (None, "", [])}
    if not clean:
        return path
    return path + "?" + _up.urlencode(clean)


def _expect_ok(status, body, what):
    """Raise on transport-level failure shapes Gumroad uses for real errors."""
    if body is None:
        raise RuntimeError("Gumroad %s returned HTTP %s with no parsable body" % (what, status))
    if not body.get("success", True) and status not in (200, 201):
        msg = body.get("message") or (body.get("error") or {}).get("message") or str(body)[:160]
        raise RuntimeError("Gumroad %s failed (HTTP %s): %s" % (what, status, msg))
    return body


def _quote(segment):
    import urllib.parse as _up
    return _up.quote(str(segment), safe="")


def _prod_summary(p):
    """Compact, receipt-friendly product row (no long HTML descriptions)."""
    if not isinstance(p, dict):
        return None
    return {
        "id": p.get("id"),
        "name": p.get("name"),
        "price_cents": p.get("price"),
        "currency": p.get("currency"),
        "published": p.get("published"),
        "sales_count": p.get("sales_count"),
        "url": p.get("short_url"),
    }


def _sale_summary(s):
    if not isinstance(s, dict):
        return None
    return {
        "id": s.get("id"),
        "product_id": s.get("product_id"),
        "product_name": (s.get("product_name") or "")[:80],
        "email": s.get("email"),
        "price_cents": s.get("price"),
        "currency": s.get("currency"),
        "created_at": s.get("created_at"),
        "refunded": s.get("refunded"),
        "chargebacked": s.get("chargebacked"),
    }


# ── read commands ────────────────────────────────────────────────────


def gumroad_list_products(inputs, stamp):
    page = inputs.get("page")
    per_page = inputs.get("per_page")
    params = {}
    try:
        if page is not None and str(page).strip():
            params["page"] = int(page)
        if per_page is not None and str(per_page).strip():
            n = int(per_page)
            if not 1 <= n <= 200:
                raise RuntimeError("per_page must be 1-200")
            params["per_page"] = n
    except (TypeError, ValueError):
        raise RuntimeError("page and per_page must be integers")
    status, body = _req("GET", _q("/products", params))
    _expect_ok(status, body, "list products")
    products = [_prod_summary(p) for p in (body.get("products") or [])]
    products = [p for p in products if p]
    return {
        "ok": True,
        "loaded_from": "module:levellerco/gumroad-seller-ops",
        "http_status": status,
        "count": len(products),
        "products": products,
    }, None


def gumroad_get_product(inputs, stamp):
    pid = inputs.get("product_id")
    if not isinstance(pid, str) or not pid.strip():
        raise RuntimeError("product_id must be a non-empty string")
    status, body = _req("GET", "/products/" + _quote(pid.strip()))
    _expect_ok(status, body, "get product")
    p = body.get("product") or {}
    return {
        "ok": True,
        "loaded_from": "module:levellerco/gumroad-seller-ops",
        "http_status": status,
        "product_id": p.get("id"),
        "name": p.get("name"),
        "price_cents": p.get("price"),
        "currency": p.get("currency"),
        "published": p.get("published"),
        "sales_count": p.get("sales_count"),
        "url": p.get("short_url"),
    }, None


def _fetch_sales(inputs):
    """Shared sale fetch for summary + detail rows."""
    params = {}
    for k in ("after", "before"):
        v = inputs.get(k)
        if isinstance(v, str) and v.strip():
            params[k] = v.strip()
    pid = inputs.get("product_id")
    if isinstance(pid, str) and pid.strip():
        params["product_id"] = pid.strip()  # _q urlencodes once
    status, body = _req("GET", _q("/sales", params))
    _expect_ok(status, body, "list sales")
    return status, (body.get("sales") or [])


def gumroad_sales_summary(inputs, stamp):
    status, sales = _fetch_sales(inputs)
    gross = 0
    net = 0
    currency = None
    live = 0
    for s in sales:
        if not isinstance(s, dict) or s.get("refunded") or s.get("chargebacked"):
            continue
        live += 1
        price = s.get("price") or 0
        gross += price
        net += price - (s.get("fee") or 0)
        currency = s.get("currency") or currency
    return {
        "ok": True,
        "loaded_from": "module:levellerco/gumroad-seller-ops",
        "http_status": status,
        "sales_count": live,
        "total_rows": len(sales),
        "gross_cents": gross,
        "net_cents": net,
        "currency": currency,
    }, None


def gumroad_list_sales(inputs, stamp):
    status, sales = _fetch_sales(inputs)
    limit = inputs.get("limit")
    rows = [_sale_summary(s) for s in sales]
    rows = [r for r in rows if r]
    if limit is not None:
        try:
            rows = rows[: max(0, int(limit))]
        except (TypeError, ValueError):
            raise RuntimeError("limit must be an integer")
    return {
        "ok": True,
        "loaded_from": "module:levellerco/gumroad-seller-ops",
        "http_status": status,
        "sales_count": len(rows),
        "sales": rows,
    }, None


def gumroad_verify_license(inputs, stamp):
    pid = inputs.get("product_id")
    key = inputs.get("license_key")
    if not isinstance(pid, str) or not pid.strip():
        raise RuntimeError("product_id must be a non-empty string")
    if not isinstance(key, str) or not key.strip():
        raise RuntimeError("license_key must be a non-empty string")
    inc = inputs.get("increment_uses_count")
    form = {
        "product_id": pid.strip(),
        "license_key": key.strip(),
        "increment_uses_count": "true" if str(inc).lower() in ("true", "1", "yes") else "false",
    }
    status, body = _req("POST", "/licenses/verify", form)
    if status == 404:
        # A nonexistent/invalid license is a normal verify answer, not a failure.
        msg = (body or {}).get("message") or "license not found for this product"
        return {
            "ok": True,
            "loaded_from": "module:levellerco/gumroad-seller-ops",
            "http_status": status,
            "valid": False,
            "message": msg,
            "uses": None,
            "purchase_email": None,
        }, None
    _expect_ok(status, body, "verify license")
    lic = body.get("license") or {}
    purchase = body.get("purchase") or {}
    return {
        "ok": True,
        "loaded_from": "module:levellerco/gumroad-seller-ops",
        "http_status": status,
        "valid": bool(lic.get("success")),
        "uses": lic.get("uses"),
        "purchase_email": purchase.get("email"),
        "refunded": purchase.get("refunded"),
        "disabled": lic.get("disabled"),
    }, None


def gumroad_list_subscribers(inputs, stamp):
    pid = inputs.get("product_id")
    if not isinstance(pid, str) or not pid.strip():
        raise RuntimeError("product_id must be a non-empty string")
    status, body = _req("GET", "/products/" + _quote(pid.strip()) + "/subscribers")
    _expect_ok(status, body, "list subscribers")
    subs = []
    for s in (body.get("subscribers") or []):
        if not isinstance(s, dict):
            continue
        subs.append({
            "id": s.get("id"),
            "email": s.get("email"),
            "product_id": s.get("product_id"),
            "created_at": s.get("created_at"),
            "cancelled_at": s.get("cancelled_at"),
        })
    return {
        "ok": True,
        "loaded_from": "module:levellerco/gumroad-seller-ops",
        "http_status": status,
        "subscribers_count": len(subs),
        "subscribers": subs,
    }, None


def gumroad_list_emails(inputs, stamp):
    status, body = _req("GET", "/emails")
    _expect_ok(status, body, "list audience emails")
    rows = []
    for e in (body.get("emails") or []):
        if not isinstance(e, dict):
            continue
        rows.append({
            "email": e.get("email"),
            "created_at": e.get("created_at"),
            "purchase_ids": e.get("purchase_ids"),
            "imported": e.get("imported"),
        })
    return {
        "ok": True,
        "loaded_from": "module:levellerco/gumroad-seller-ops",
        "http_status": status,
        "emails_count": len(rows),
        "emails": rows,
    }, None


# ── write commands (airlock-gated) ───────────────────────────────────


def gumroad_create_offer_code(inputs, stamp):
    pid = inputs.get("product_id")
    name = inputs.get("name")
    amount = inputs.get("amount_off")
    if not isinstance(pid, str) or not pid.strip():
        raise RuntimeError("product_id must be a non-empty string")
    if not isinstance(name, str) or not name.strip():
        raise RuntimeError("name must be a non-empty string")
    if len(name.strip()) > 60:
        raise RuntimeError("name must be 60 characters or fewer")
    try:
        amount_val = float(amount)
    except (TypeError, ValueError):
        raise RuntimeError("amount_off must be a number")
    if amount_val <= 0:
        raise RuntimeError("amount_off must be positive")
    offer_type = str(inputs.get("offer_type") or "fixed").strip().lower()
    if offer_type not in ("fixed", "percent"):
        raise RuntimeError("offer_type must be 'fixed' or 'percent'")
    if offer_type == "percent" and amount_val != int(amount_val):
        raise RuntimeError("percent amount_off must be a whole number of percent")

    form = {"name": name.strip(), "amount_off": str(int(amount_val) if amount_val == int(amount_val) else amount_val)}
    if offer_type == "percent":
        form["offer_type"] = "percent"
    mpc = inputs.get("max_purchase_count")
    if mpc is not None and str(mpc).strip():
        try:
            form["max_purchase_count"] = str(int(mpc))
        except (TypeError, ValueError):
            raise RuntimeError("max_purchase_count must be an integer")

    status, body = _req("POST", "/products/" + _quote(pid.strip()) + "/offer_codes", form)
    _expect_ok(status, body, "create offer code")
    oc = body.get("offer_code") or {}
    return {
        "ok": True,
        "loaded_from": "module:levellerco/gumroad-seller-ops",
        "http_status": status,
        "offer_code_id": oc.get("id"),
        "name": oc.get("name"),
        "amount_cents": oc.get("amount_cents"),
        "percent_off": oc.get("percent_off"),
    }, None


def gumroad_list_offer_codes(inputs, stamp):
    pid = inputs.get("product_id")
    if not isinstance(pid, str) or not pid.strip():
        raise RuntimeError("product_id must be a non-empty string")
    status, body = _req("GET", "/products/" + _quote(pid.strip()) + "/offer_codes")
    _expect_ok(status, body, "list offer codes")
    rows = []
    for oc in (body.get("offer_codes") or []):
        if not isinstance(oc, dict):
            continue
        rows.append({
            "id": oc.get("id"),
            "name": oc.get("name"),
            "amount_cents": oc.get("amount_cents"),
            "percent_off": oc.get("percent_off"),
            "times_used": oc.get("times_used"),
            "max_purchase_count": oc.get("max_purchase_count"),
        })
    return {
        "ok": True,
        "loaded_from": "module:levellerco/gumroad-seller-ops",
        "http_status": status,
        "offer_codes_count": len(rows),
        "offer_codes": rows,
    }, None


def gumroad_delete_offer_code(inputs, stamp):
    pid = inputs.get("product_id")
    ocid = inputs.get("offer_code_id")
    if not isinstance(pid, str) or not pid.strip():
        raise RuntimeError("product_id must be a non-empty string")
    if not isinstance(ocid, str) or not ocid.strip():
        raise RuntimeError("offer_code_id must be a non-empty string")
    status, body = _req("DELETE", "/products/" + _quote(pid.strip()) + "/offer_codes/" + _quote(ocid.strip()))
    _expect_ok(status, body, "delete offer code")
    return {
        "ok": True,
        "loaded_from": "module:levellerco/gumroad-seller-ops",
        "http_status": status,
        "deleted": bool((body or {}).get("success")),
        "offer_code_id": ocid.strip(),
    }, None


def gumroad_update_price(inputs, stamp):
    pid = inputs.get("product_id")
    price = inputs.get("price_cents")
    if not isinstance(pid, str) or not pid.strip():
        raise RuntimeError("product_id must be a non-empty string")
    try:
        price_val = int(price)
    except (TypeError, ValueError):
        raise RuntimeError("price_cents must be an integer number of pence/cents")
    if price_val < 0 or price_val > 10_000_00:
        raise RuntimeError("price_cents must be between 0 and 1,000,000 (10k in major units)")
    status, body = _req("PUT", "/products/" + _quote(pid.strip()), {"price": str(price_val)})
    _expect_ok(status, body, "update price")
    p = body.get("product") or {}
    return {
        "ok": True,
        "loaded_from": "module:levellerco/gumroad-seller-ops",
        "http_status": status,
        "product_id": p.get("id") or pid.strip(),
        "price_cents": p.get("price"),
        "currency": p.get("currency"),
    }, None
