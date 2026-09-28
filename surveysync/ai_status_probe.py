"""Private subprocess entrypoint for bounded Foundry capability inspection."""
from __future__ import annotations

import json
from pathlib import Path
import sys


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit('Expected an owned result path and model alias.')
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from surveysync.ai_runtime import _probe_foundry_local_direct
    status = _probe_foundry_local_direct(sys.argv[2])
    Path(sys.argv[1]).write_text(json.dumps(status.to_dict()), encoding='utf-8')


if __name__ == '__main__':
    main()
