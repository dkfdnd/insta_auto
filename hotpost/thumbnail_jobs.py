"""CLI for preparing/resuming Flow thumbnail jobs, without regenerating TTS."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .flow_image_adapter import GoogleFlowImageAdapter
from .thumbnail_planner import create_plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--job-dir", required=True, type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--brief", required=True, type=Path,
                         help="JSON: subject, script, feature, preferred, claims (last three optional)")
    prepare.add_argument("--reference", action="append", required=True, type=Path)
    accept = commands.add_parser("accept")
    accept.add_argument("--image", required=True, type=Path)
    accept.add_argument("--flow-url", required=True)
    accept.add_argument("--reviewed", action="store_true")
    commands.add_parser("export")
    args = parser.parse_args()
    adapter = GoogleFlowImageAdapter(args.data_root)
    if args.command == "prepare":
        brief = json.loads(args.brief.read_text(encoding="utf-8"))
        value = adapter.prepare(args.job_dir, create_plan(**brief), args.reference)
    elif args.command == "accept":
        value = adapter.accept_image(args.job_dir, args.image,
                                     flow_url=args.flow_url, reviewed=args.reviewed)
    else:
        value = adapter.editing_thumbnail(args.job_dir)
    print(json.dumps(value, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
