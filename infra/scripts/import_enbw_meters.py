#!/usr/bin/env python3
"""Bulk-import the EnBW Zähler inventory into the WHV backend.

Reads ``enbw_meters.json`` (next to this script), matches each EnBW address to
a property via ``GET /me/properties``, seeds that property's meters via the
admin bulk endpoint ``POST /admin/properties/{id}/meters/bulk``, and (unless
``--no-readings``) seeds each meter's current EnBW Zählerstand as an initial
reading via ``POST /admin/meters/{id}/readings``. Stdlib only — no pip install.

Auth: a VERWALTER access token, passed with ``--token`` or the ``WHV_ADMIN_TOKEN``
env var. (Grab it from the admin SPA: DevTools → Application → Local Storage →
the access-token entry, or your /auth/login response.) The token is never
printed or stored.

Modes (safe by default — nothing is written unless you pass --apply):
  python3 import_enbw_meters.py                 # offline plan: parse + totals, no network
  python3 import_enbw_meters.py --token T       # dry-run: match properties, show plan, no writes
  python3 import_enbw_meters.py --token T --apply   # create meters + seed readings

Idempotent: meters whose number already exists are not re-created, and a reading
is only seeded when the meter has zero readings — so re-running is safe.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_BASE = "https://staging.api.wagner-hausverwaltung.com"
DATA_FILE = Path(__file__).with_name("enbw_meters.json")
READING_NOTE = "EnBW WOWI Bestand (Import)"

# Fields the backend's MeterCreate accepts — everything else in the inventory
# (e.g. the per-meter `reading`, handled separately) is stripped before POST.
MC_FIELDS = {"meter_number", "meter_type", "unit_id", "description", "location",
             "unit_label", "installation_date", "calibration_valid_until",
             "supplier_name", "supplier_email"}


def norm_street(s: str) -> str:
    s = (s or "").strip().lower()
    s = s.replace("straße", "str").replace("strasse", "str")
    return s.replace(".", "").replace(" ", "")


def norm_num(n: str) -> str:
    return (n or "").strip().lower().replace(" ", "")


def _send(req):
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode()
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw


def http_json(base, method, path, token, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base.rstrip("/") + path, data=data, method=method)
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    return _send(req)


def post_multipart(base, path, token, fields):
    boundary = "----WHVMetersImportBoundary7f3c1a9"
    parts = []
    for k, v in fields.items():
        parts += [f"--{boundary}",
                  f'Content-Disposition: form-data; name="{k}"', "", str(v)]
    parts += [f"--{boundary}--", ""]
    body = "\r\n".join(parts).encode()
    req = urllib.request.Request(base.rstrip("/") + path, data=body, method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    req.add_header("Accept", "application/json")
    req.add_header("Authorization", f"Bearer {token}")
    return _send(req)


def find_property(props, match):
    """Match on PLZ + house number + normalised street, requiring EQUALITY
    (norm_street already folds 'straße'->'str' and strips dots/spaces, so the
    common abbreviations still match). Returns (property, reason): reason is
    set when we deliberately decline — "ambiguous" if more than one property
    shares the same PLZ+street+number — so the caller never silently writes to
    the wrong Liegenschaft."""
    pc = (match["postal_code"] or "").strip()
    ms, mn = norm_street(match["street"]), norm_num(match["number"])
    cands = [
        p for p in props
        if (p.get("postal_code") or "").strip() == pc
        and norm_num(p.get("number", "")) == mn
        and norm_street(p.get("street", "")) == ms
    ]
    if len(cands) == 1:
        return cands[0], None
    if len(cands) > 1:
        return None, f"ambiguous — {len(cands)} properties share this PLZ+street+number"
    return None, None


def main() -> int:
    ap = argparse.ArgumentParser(description="Bulk-import EnBW meters + initial readings.")
    ap.add_argument("--base", default=os.environ.get("WHV_API_BASE", DEFAULT_BASE),
                    help=f"API base URL (default {DEFAULT_BASE})")
    ap.add_argument("--token", default=os.environ.get("WHV_ADMIN_TOKEN"),
                    help="VERWALTER access token (or set WHV_ADMIN_TOKEN)")
    ap.add_argument("--data", default=str(DATA_FILE), help="inventory JSON path")
    ap.add_argument("--apply", action="store_true", help="actually write (otherwise dry-run)")
    ap.add_argument("--no-readings", action="store_true", help="create meters only, skip initial readings")
    args = ap.parse_args()
    seed_readings = not args.no_readings

    inv = json.loads(Path(args.data).read_text())["properties"]
    total = sum(len(p["meters"]) for p in inv)
    n_readings = sum(1 for p in inv for m in p["meters"] if m.get("reading"))
    by_type: dict[str, int] = {}
    for p in inv:
        for m in p["meters"]:
            by_type[m["meter_type"]] = by_type.get(m["meter_type"], 0) + 1
    print(f"Inventory: {len(inv)} properties, {total} meters "
          f"({', '.join(f'{k} {v}' for k, v in sorted(by_type.items()))}), "
          f"{n_readings} initial readings")

    if not args.token:
        print("\nOffline plan (no token given — nothing fetched or written):")
        for p in inv:
            m = p["match"]
            print(f"  {m['postal_code']} {m['street']} {m['number']}: "
                  + ", ".join(x["meter_number"] + " [" + x["meter_type"]
                              + ("•R" if x.get("reading") else "") + "]" for x in p["meters"]))
        print("\nPass --token (VERWALTER) to match against live properties, then --apply to write.")
        return 0

    status, props = http_json(args.base, "GET", "/me/properties", args.token)
    if status != 200 or not isinstance(props, list):
        print(f"ERROR: GET /me/properties -> {status}: {props}", file=sys.stderr)
        return 1
    print(f"Fetched {len(props)} properties from {args.base}\n")

    made, skipped, r_made, r_skipped, unmatched, errors = 0, 0, 0, 0, [], 0
    for p in inv:
        m = p["match"]
        label = f"{m['postal_code']} {m['street']} {m['number']}"
        prop, why = find_property(props, m)
        if not prop:
            unmatched.append(label + (f" [{why}]" if why else ""))
            print(f"  ✗ NO MATCH: {label}" + (f" ({why})" if why else ""))
            continue
        tag = prop.get("name") or label

        status, existing = http_json(args.base, "GET", f"/admin/properties/{prop['id']}/meters", args.token)
        if status != 200 or not isinstance(existing, list):
            print(f"  ✗ {label} → {tag}: could not list existing meters ({status}) — "
                  "skipping to avoid duplicates", file=sys.stderr)
            errors += 1
            continue
        by_num = {e["meter_number"].strip(): e for e in existing}
        to_create = [x for x in p["meters"] if x["meter_number"].strip() not in by_num]
        skipped += len(p["meters"]) - len(to_create)

        # --- create meters ---
        if to_create:
            if args.apply:
                payload = [{k: v for k, v in x.items() if k in MC_FIELDS} for x in to_create]
                status, resp = http_json(args.base, "POST",
                                         f"/admin/properties/{prop['id']}/meters/bulk",
                                         args.token, {"meters": payload})
                if status not in (200, 201) or not isinstance(resp, dict):
                    print(f"  ✗ {label} → {tag}: bulk POST {status}: {resp}", file=sys.stderr)
                    errors += 1
                    continue
                for c in resp.get("created", []):
                    by_num[c["meter_number"].strip()] = c
                made += len(resp.get("created", []))
                if resp.get("errors"):
                    errors += len(resp["errors"])
                    print(f"  ! {label} → {tag}: {len(resp['errors'])} create errors: {resp['errors']}",
                          file=sys.stderr)
            else:
                for x in to_create:
                    by_num[x["meter_number"].strip()] = {"meter_number": x["meter_number"],
                                                         "id": None, "reading_count": 0}
                made += len(to_create)

        # --- seed initial readings (only for meters with zero readings) ---
        seeded_here = 0
        if seed_readings:
            for x in p["meters"]:
                r = x.get("reading")
                if not r:
                    continue
                meter = by_num.get(x["meter_number"].strip())
                if not meter:
                    continue  # create failed
                if (meter.get("reading_count") or 0) > 0:
                    r_skipped += 1
                    continue
                if args.apply and meter.get("id"):
                    st, rb = post_multipart(
                        args.base, f"/admin/meters/{meter['id']}/readings", args.token,
                        {"value": r["value"], "read_on": r["read_on"],
                         "source": "MANUAL", "note": READING_NOTE})
                    if st in (200, 201):
                        r_made += 1
                        seeded_here += 1
                    else:
                        errors += 1
                        print(f"  ! {label}/{x['meter_number']}: reading POST {st}: {rb}", file=sys.stderr)
                else:
                    r_made += 1
                    seeded_here += 1

        n_new = len([x for x in to_create])
        verb = "created" if args.apply else "would create"
        rverb = "seeded" if args.apply else "would seed"
        if n_new or seeded_here:
            print(f"  {'✓' if args.apply else '+'} {label} → {tag}: {verb} {n_new} meters"
                  + (f", {rverb} {seeded_here} readings" if seeded_here else "")
                  + (f" (skip {len(p['meters']) - n_new} existing)" if len(p["meters"]) - n_new else ""))
        else:
            print(f"  = {label} → {tag}: nothing to do (all present)")

    verb = "created" if args.apply else "would create"
    print(f"\nDone. {verb} {made} meters, {('seeded' if args.apply else 'would seed')} {r_made} readings; "
          f"skipped {skipped} existing meters, {r_skipped} meters already had readings.")
    if errors:
        print(f"  {errors} error(s) — see stderr above.", file=sys.stderr)
    if unmatched:
        print(f"  {len(unmatched)} UNMATCHED properties: {unmatched}")
    elif not args.apply:
        print("All matched. Re-run with --apply to write.")
    # Non-zero on any unmatched/errors in BOTH modes, so a dry-run that fails to
    # match cleanly can gate a wrapper before --apply.
    return 1 if (unmatched or errors) else 0


if __name__ == "__main__":
    sys.exit(main())
