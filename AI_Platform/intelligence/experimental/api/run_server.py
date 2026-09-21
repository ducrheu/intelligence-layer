from __future__ import annotations

import argparse
from pathlib import Path

from .server import build_server


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local-only Phase 2 Intelligence API.")
    parser.add_argument("--root", type=Path, default=Path("AI_Platform/intelligence"))
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = build_server(args.root, "127.0.0.1", args.port)
    print(f"Listening on http://{server.server_address[0]}:{server.server_address[1]}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
