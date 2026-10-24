#!/usr/bin/env python3
"""Print allowlisted project documentation without network access or side effects."""

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs/partners/agent-context.json"


def main():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    topics = manifest["topics"]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("topics", nargs="*", help="Context topics (see --list)")
    parser.add_argument("--list", action="store_true", help="List available topics")
    parser.add_argument("--json", action="store_true", help="Emit structured JSON")
    args = parser.parse_args()
    if args.list:
        if args.json:
            print(json.dumps(manifest, indent=2))
        else:
            for name, item in topics.items():
                print(f"{name:14} {item['description']}")
        return

    selected = list(dict.fromkeys(args.topics or [manifest["default_topic"]]))
    unknown = [topic for topic in selected if topic not in topics]
    if unknown:
        parser.error(f"Unknown topic(s): {', '.join(unknown)}. Use --list.")
    documents = []
    for topic in selected:
        item = topics[topic]
        path = (ROOT / item["path"]).resolve()
        if not path.is_relative_to(ROOT / "docs/partners"):
            parser.error(f"Topic {topic!r} resolves outside partner documentation")
        documents.append({
            "topic": topic,
            "path": item["path"],
            "research_date": manifest["research_date"],
            "content": path.read_text(encoding="utf-8"),
        })
    if args.json:
        print(json.dumps(documents, indent=2, ensure_ascii=False))
    else:
        print("\n\n".join(
            f"<!-- {doc['path']} | researched {doc['research_date']} -->\n{doc['content']}"
            for doc in documents
        ))


if __name__ == "__main__":
    main()
