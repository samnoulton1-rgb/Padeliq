#!/usr/bin/env python3
"""Refresh the read-only club directory from public OpenStreetMap data."""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

OVERPASS_ENDPOINTS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)
OVERPASS_QUERY = """
[out:json][timeout:120];
area["boundary"="administrative"]["name"="Greater London"]->.london;
area["boundary"="administrative"]["name"="Kent"]["admin_level"="6"]->.kent;
area["boundary"="administrative"]["name"="Essex"]["admin_level"="6"]->.essex;
(
  nwr(area.london)["sport"~"(^|;|,)padel($|;|,)",i];
  nwr(area.kent)["sport"~"(^|;|,)padel($|;|,)",i];
  nwr(area.essex)["sport"~"(^|;|,)padel($|;|,)",i];
  nwr(area.london)["leisure"]["name"~"padel",i];
  nwr(area.kent)["leisure"]["name"~"padel",i];
  nwr(area.essex)["leisure"]["name"~"padel",i];
);
out center tags;
""".strip()


def fetch_overpass() -> dict[str, Any]:
    encoded = urllib.parse.urlencode({"data": OVERPASS_QUERY}).encode()
    for endpoint in OVERPASS_ENDPOINTS:
        request = urllib.request.Request(
            endpoint,
            data=encoded,
            headers={
                "User-Agent": "PadelIQ-ClubDirectory/1.0 (https://github.com/samnoulton1-rgb/Padeliq)",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=150) as response:
                return json.load(response)
        except Exception as exc:
            print(f"{endpoint} failed: {exc}", file=sys.stderr)
    raise RuntimeError("Every configured Overpass endpoint failed; the existing directory was left unchanged")


def coordinates(element: dict[str, Any]) -> tuple[float | None, float | None]:
    centre = element.get("center") or element
    try:
        return float(centre["lat"]), float(centre["lon"])
    except (KeyError, TypeError, ValueError):
        return None, None


def classify_region(lat: float | None, lon: float | None, postcode: str) -> str | None:
    if lat is None or lon is None:
        return None
    # Greater London boundary, with central/outer presentation split.
    if 51.27 <= lat <= 51.71 and -0.53 <= lon <= 0.34:
        central_distance = ((lat - 51.5074) ** 2 + ((lon + 0.1278) * 0.63) ** 2) ** 0.5
        outer_postcodes = ("BR", "CR", "DA", "EN", "HA", "IG", "KT", "RM", "SM", "TW", "UB")
        return "Outer London" if central_distance > 0.16 or postcode.upper().startswith(outer_postcodes) else "London"
    if 51.39 <= lat <= 52.15 and 0.30 <= lon <= 1.35:
        return "Essex"
    if 50.85 <= lat <= 51.52 and -0.02 <= lon <= 1.52:
        return "Kent"
    return None


def external_url(value: str | None) -> str:
    if not value:
        return ""
    candidate = value.strip()
    if candidate.startswith("www."):
        candidate = f"https://{candidate}"
    parsed = urllib.parse.urlparse(candidate)
    return candidate if parsed.scheme in {"http", "https"} and parsed.netloc else ""


def normalise_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def transform(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for element in payload.get("elements", []):
        tags = element.get("tags") or {}
        name = (tags.get("name") or tags.get("operator") or tags.get("brand") or "").strip()
        if not name or re.fullmatch(r"(?:show\s+)?court\s*\d+|padel\s*\d+", name, flags=re.IGNORECASE):
            continue
        lat, lon = coordinates(element)
        postcode = str(tags.get("addr:postcode") or "").strip()
        region = classify_region(lat, lon, postcode)
        if not region:
            continue
        locality = (
            tags.get("addr:city")
            or tags.get("addr:town")
            or tags.get("addr:village")
            or tags.get("addr:suburb")
            or tags.get("addr:place")
            or ""
        )
        area = " · ".join(part for part in (str(locality).strip(), postcode) if part) or "Location available on source map"
        courts = str(tags.get("padel:courts") or tags.get("courts") or tags.get("capacity") or "See venue")
        indoor = str(tags.get("indoor") or "").lower() in {"yes", "true", "1"}
        covered = str(tags.get("covered") or "").lower() in {"yes", "true", "1"}
        setting = "Indoor" if indoor else "Covered" if covered else "Outdoor"
        website = external_url(
            tags.get("contact:website") or tags.get("website") or tags.get("booking:website") or tags.get("url")
        )
        element_type, element_id = element.get("type", "node"), element.get("id")
        source = f"https://www.openstreetmap.org/{element_type}/{element_id}"
        key = f"{normalise_name(name)}:{region}:{normalise_name(str(locality))}"
        candidate = {
            "name": name,
            "region": region,
            "area": area,
            "courts": courts,
            "setting": setting,
            "website": website or source,
            "source": source,
            "latitude": round(lat, 6) if lat is not None else None,
            "longitude": round(lon, 6) if lon is not None else None,
        }
        existing = rows.get(key)
        if existing is None or (not existing["website"] and candidate["website"]):
            rows[key] = candidate
    return sorted(rows.values(), key=lambda row: (row["region"], row["name"].casefold()))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, help="Use an Overpass JSON fixture instead of the network")
    parser.add_argument("--output", type=Path, default=Path("data/club-directory.json"))
    parser.add_argument("--minimum", type=int, default=3)
    parser.add_argument("--respect-interval", action="store_true", help="Skip if the existing feed is less than three days old")
    args = parser.parse_args()
    if args.respect_interval and args.output.exists():
        try:
            existing = json.loads(args.output.read_text())
            generated_at = datetime.fromisoformat(existing["generated_at"])
            if datetime.now(timezone.utc) - generated_at < timedelta(days=3):
                print("The directory is less than three days old; no refresh is required")
                return 0
        except (KeyError, ValueError, TypeError, json.JSONDecodeError):
            pass
    payload = json.loads(args.input.read_text()) if args.input else fetch_overpass()
    rows = transform(payload)
    if len(rows) < args.minimum:
        raise RuntimeError(f"Only {len(rows)} valid venues were returned; refusing to replace the existing directory")
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    document = {
        "generated_at": generated_at,
        "refresh_interval_days": 3,
        "source": "OpenStreetMap contributors via Overpass API",
        "source_url": "https://www.openstreetmap.org/copyright",
        "license": "ODbL 1.0",
        "regions": ["London", "Outer London", "Kent", "Essex"],
        "clubs": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n")
    print(f"Wrote {len(rows)} public venues to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
