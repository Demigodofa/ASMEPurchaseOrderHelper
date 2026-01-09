import json
import os
from datetime import datetime, timezone


def load_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def main():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    output_root = os.path.join(repo_root, "sectionII_partA_data_digitized")
    toc_index_path = os.path.join(output_root, "toc_index_pass10.json")

    toc_index = load_json(toc_index_path)
    entries = toc_index.get("entries", [])

    report = {
        "createdUtc": datetime.now(timezone.utc).isoformat(),
        "orderMismatches": [],
        "summary": {
            "entries": len(entries),
            "orderMismatches": 0,
        },
    }

    last = None
    for entry in entries:
        start = entry.get("startGlobalPage")
        spec = entry.get("spec")
        if start is None:
            continue
        if last is not None and start < last["startGlobalPage"]:
            report["summary"]["orderMismatches"] += 1
            report["orderMismatches"].append(
                {
                    "spec": spec,
                    "startGlobalPage": start,
                    "previousSpec": last["spec"],
                    "previousStartGlobalPage": last["startGlobalPage"],
                }
            )
        last = {"spec": spec, "startGlobalPage": start}

    out_path = os.path.join(output_root, "toc_order_pass10c.json")
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)

    print("TOC order pass complete.")


if __name__ == "__main__":
    main()
