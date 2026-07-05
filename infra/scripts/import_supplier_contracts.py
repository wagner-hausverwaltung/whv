#!/usr/bin/env python3
"""Bulk-import the Versorgungsverträge worksheet into the WHV backend.

Reads ``supplier_contracts_data.json`` (next to this script; parsed from
Luis's ``02 Dienstleister.xlsx`` — one sheet per Objekt, sheet codes like
``B11`` / ``W60`` / ``B6,8``), resolves each sheet code to a property via
``GET /admin/properties`` (first street letter + house number, refusing
ambiguity), links Zähler numbers to the property's meters, and creates the
contracts via ``POST /admin/properties/{id}/supplier-contracts``.

IBAN / e-mail / phone from the worksheet are deliberately NOT imported —
they belong on the Impower Dienstleister contact, not on the contract.

Auth: a VERWALTER access token via ``--token`` or ``WHV_ADMIN_TOKEN``.

Modes (safe by default — nothing is written unless you pass --apply):
  python3 import_supplier_contracts.py              # offline plan, no network
  python3 import_supplier_contracts.py --token T    # dry-run: resolve + plan
  python3 import_supplier_contracts.py --token T --apply

Idempotent: a row is skipped when the property already has a contract with
the same category + provider + contract/customer number — re-running is safe.
Ends with a completeness report (sheets without property, properties without
sheet, unmatched Zähler).
"""

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_BASE = "https://api.wagner-hausverwaltung.com"
DATA_FILE = Path(__file__).with_name("supplier_contracts_data.json")

# Pin a sheet code to a specific property id when the heuristic can't decide
# (e.g. one address hosting a WEG *and* an SEV). code -> property id.
OVERRIDES: dict[str, str] = {}


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


def parse_code(code: str):
    """'B11' -> ('b', '11'); 'B6,8' -> ('b', '6'); 'U204A' -> ('u', '204a');
    'M 8' -> ('m', '8'); 'FTS67' -> ('f', '67')."""
    m = re.match(r"^([A-Za-z]+)\s*([\d,./ ]+[A-Za-z]?)$", code.strip())
    if not m:
        return None
    letters, num = m.group(1).lower(), m.group(2).lower()
    first_num = re.split(r"[,/]", num)[0].strip().replace(" ", "")
    return letters[0], first_num


def house_numbers(number: str) -> set[str]:
    """'6, 8' -> {'6','8'}; '5/7' -> {'5','7'}; '204 A' -> {'204a'}."""
    return {
        p.strip().replace(" ", "").lower()
        for p in re.split(r"[,/]", number or "")
        if p.strip()
    }


def resolve_property(code: str, props: list) -> tuple[dict | None, str]:
    if code in OVERRIDES:
        for p in props:
            if str(p["id"]) == OVERRIDES[code]:
                return p, "pinned via OVERRIDES"
        return None, f"OVERRIDES id {OVERRIDES[code]} not found"
    parsed = parse_code(code)
    if parsed is None:
        return None, "unparseable sheet code"
    letter, num = parsed
    cands = [
        p
        for p in props
        if (p.get("street") or "").strip().lower().startswith(letter)
        and num in house_numbers(p.get("number") or "")
    ]
    if len(cands) == 1:
        return cands[0], "matched"
    if len(cands) > 1:
        # A WEG and an SEV can share one address; supplier contracts belong to
        # the WEG (OWNER) — same call as the EnBW Allgemeinstrom meter pin.
        owners = [p for p in cands if p.get("type") == "OWNER"]
        if len(owners) == 1:
            others = ", ".join(f"{p['name']} ({p['type']})" for p in cands if p is not owners[0])
            return owners[0], f"multiple candidates — picked the WEG over: {others}"
        return None, "ambiguous: " + ", ".join(f"{p['name']} ({p['type']})" for p in cands)
    return None, "no property matched"


def meter_id_for(number: str, meters: list) -> str | None:
    if not number:
        return None
    wanted = number.strip().lower()
    for m in meters:
        if (m.get("meter_number") or "").strip().lower() == wanted:
            return str(m["id"])
    # 'W60'-style entries prefix the OBIS medium ('1/TR00…'); retry without it.
    if "/" in wanted:
        tail = wanted.split("/", 1)[1]
        for m in meters:
            if (m.get("meter_number") or "").strip().lower() == tail:
                return str(m["id"])
    return None


def contract_key(c: dict) -> tuple:
    return (
        (c.get("category") or "").strip().upper(),
        (c.get("provider_name") or "").strip().lower(),
        (c.get("contract_number") or "").strip(),
        (c.get("customer_number") or "").strip(),
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Bulk-import Versorgungsverträge.")
    ap.add_argument("--base", default=os.environ.get("WHV_API_BASE", DEFAULT_BASE))
    ap.add_argument("--token", default=os.environ.get("WHV_ADMIN_TOKEN"))
    ap.add_argument("--data", default=str(DATA_FILE))
    ap.add_argument("--apply", action="store_true", help="actually write (otherwise dry-run)")
    args = ap.parse_args()

    data: dict = json.load(open(args.data, encoding="utf-8"))
    total = sum(len(v) for v in data.values())
    print(f"Worksheet: {len(data)} sheets, {total} contract rows")
    if not args.token:
        for code, rows in data.items():
            print(f"  {code}: {len(rows)} rows")
        print("\nNo --token/WHV_ADMIN_TOKEN — offline plan only.")
        return 0

    st, props = http_json(args.base, "GET", "/admin/properties", args.token)
    if st != 200:
        print(f"GET /admin/properties -> {st}: {props}", file=sys.stderr)
        return 1
    print(f"API: {len(props)} properties @ {args.base}\n")

    created = skipped = failed = 0
    unmatched_sheets: list[str] = []
    unmatched_meters: list[str] = []
    matched_property_ids: set[str] = set()

    for code, rows in data.items():
        prop, reason = resolve_property(code, props)
        if prop is None:
            unmatched_sheets.append(f"{code} ({reason})")
            print(f"## {code}: SKIPPED — {reason}")
            continue
        matched_property_ids.add(str(prop["id"]))
        label = f"{prop.get('street', '')} {prop.get('number', '')}".strip() or prop["name"]
        print(f"## {code} -> {prop['name']} [{label}] ({reason})")

        st, existing = http_json(
            args.base, "GET", f"/admin/properties/{prop['id']}/supplier-contracts", args.token
        )
        if st != 200:
            print(f"  GET supplier-contracts -> {st}: {existing}", file=sys.stderr)
            return 1
        existing_keys = {contract_key(c) for c in existing}
        st, meters = http_json(
            args.base, "GET", f"/admin/properties/{prop['id']}/meters", args.token
        )
        if st != 200:
            meters = []

        for r in rows:
            body = {
                "category": r["category"],
                "provider_name": r["provider_name"],
                "customer_number": r["customer_number"] or None,
                "contract_number": r["contract_number"] or None,
                "notes": r["notes"] or None,
            }
            if contract_key(body) in existing_keys:
                skipped += 1
                print(f"  = exists: {r['category']:<18} {r['provider_name']}")
                continue
            mid = meter_id_for(r["meter_number"], meters)
            if r["meter_number"] and mid is None:
                unmatched_meters.append(f"{code}: {r['provider_name']} Zähler {r['meter_number']}")
            if mid:
                body["meter_id"] = mid
            zi = " ⇒ Zähler ✓" if mid else (f" (Zähler {r['meter_number']} NICHT gefunden)" if r["meter_number"] else "")
            if not args.apply:
                print(f"  + would create: {r['category']:<18} {r['provider_name']}{zi}")
                created += 1
                continue
            st, resp = http_json(
                args.base,
                "POST",
                f"/admin/properties/{prop['id']}/supplier-contracts",
                args.token,
                body,
            )
            if st == 201:
                created += 1
                print(f"  + created: {r['category']:<18} {r['provider_name']}{zi}")
            else:
                failed += 1
                print(f"  ! FAILED ({st}): {r['provider_name']} — {resp}", file=sys.stderr)

    mode = "created" if args.apply else "would create"
    print(f"\n== {mode}: {created} · skipped (existing): {skipped} · failed: {failed}")
    if unmatched_sheets:
        print("\nSheets without a matched property:")
        for s in unmatched_sheets:
            print(f"  - {s}")
    no_sheet = [
        f"{p['name']} ({p.get('street','')} {p.get('number','')})".strip()
        for p in props
        if str(p["id"]) not in matched_property_ids
    ]
    if no_sheet:
        print(f"\nProperties WITHOUT a worksheet sheet ({len(no_sheet)}) — completeness gaps:")
        for s in sorted(no_sheet):
            print(f"  - {s}")
    if unmatched_meters:
        print("\nZähler numbers not found on the property (no link set):")
        for s in unmatched_meters:
            print(f"  - {s}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
