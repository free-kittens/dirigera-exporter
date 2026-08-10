#!/usr/bin/env python3
"""Dump all Dirigera devices to JSON using credentials from .env.

Usage:
  python scripts/dump_devices.py --out devices.json

The script reads DIRIGERA_HOST (or IP) and DIRIGERA_TOKEN (or token) from the environment/.env.
"""
import os
import json
import argparse
import datetime
from dotenv import load_dotenv

load_dotenv()

def default_serializer(o):
    if isinstance(o, datetime.datetime):
        try:
            return o.isoformat()
        except Exception:
            return str(o)
    try:
        return o.__dict__
    except Exception:
        return repr(o)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", "-o", default="devices_dump.json", help="Output JSON file")
    args = parser.parse_args()

    host = (
        os.getenv("DIRIGERA_HOST")
        or os.getenv("IP")
        or os.getenv("HOST")
        or os.getenv("host")
        or os.getenv("ip")
    )
    token = (
        os.getenv("DIRIGERA_TOKEN")
        or os.getenv("TOKEN")
        or os.getenv("token")
    )

    if not host or not token:
        print("DIRIGERA_HOST (or IP) and DIRIGERA_TOKEN (or token) must be set in environment or .env")
        return

    try:
        import dirigera
    except Exception as e:
        print("Failed to import dirigera client:", e)
        return

    try:
        hub = dirigera.Hub(token, host)
    except Exception as e:
        print("Failed to construct Hub:", e)
        return

    out = {"host": host}

    try:
        devices = hub.get('/devices')
        out["device_count"] = len(devices) if devices is not None else 0
        out["devices"] = devices
    except Exception as e:
        out["devices_error"] = str(e)
        devices = []

    # Build a summary with selected fields for metric mapping
    summary = []
    known_attrs = set()
    values_of_interest = (
        "currentActivePower",
        "current_active_power",
        "currentAmps",
        "current_amps",
        "currentVoltage",
        "current_voltage",
        "totalEnergyConsumed",
        "total_energy_consumed",
        "batteryPercentage",
        "battery_percentage",
        "isOn",
        "is_on",
        "power",
        "power_w",
        "power_watts",
        "lightLevel",
        "light_level",
        "colorTemperature",
        "color_temperature",
    )

    def extract_attr(obj, *keys, default=None):
        if obj is None:
            return default
        if isinstance(obj, dict):
            for key in keys:
                if key in obj:
                    return obj[key]
        return default

    for device in devices or []:
        dev = device if isinstance(device, dict) else device.__dict__
        attrs = dev.get("attributes", {}) or {}
        device_summary = {
            "id": dev.get("id") or dev.get("device_id") or dev.get("uuid"),
            "type": dev.get("type") or dev.get("deviceType") or dev.get("device_type"),
            "deviceType": dev.get("deviceType") or dev.get("type") or dev.get("device_type"),
            "name": dev.get("name") or attrs.get("customName") or attrs.get("custom_name") or dev.get("display_name") or dev.get("label"),
            "room": (dev.get("room") or {}).get("name") if isinstance(dev.get("room"), dict) else None,
            "isReachable": dev.get("isReachable") or dev.get("is_reachable"),
            "lastSeen": dev.get("lastSeen") or dev.get("last_seen"),
            "attribute_keys": sorted(attrs.keys()),
            "attributes": {},
        }

        for key in values_of_interest:
            if key in attrs:
                device_summary["attributes"][key] = attrs[key]
                known_attrs.add(key)

        summary.append(device_summary)

    out["summary"] = summary
    out["observed_attribute_keys"] = sorted(list(known_attrs))

    # write output
    try:
        with open(args.out, "w") as f:
            json.dump(out, f, default=default_serializer, indent=2)
        print(f"Wrote devices to {args.out} (devices={out.get('device_count')})")
        print("Observed metric fields:", ", ".join(sorted(out["observed_attribute_keys"])))
        print("Summary sample:")
        for item in summary:
            print(json.dumps(item, ensure_ascii=False))
    except Exception as e:
        print("Failed to write output:", e)


if __name__ == "__main__":
    main()
