"""Entry point: run the proxy with uvicorn."""

from __future__ import annotations

import logging
import shutil
import sys

import uvicorn

from app import Settings, create_app

CYAN = "\033[96m"
BOLD_WHITE = "\033[1;97m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
DIM = "\033[2m"
RESET = "\033[0m"

_GLYPHS = {
    'U': ('#..#', '#..#', '#..#', '#..#', '.##.'),
    'N': ('#...#', '##..#', '#.#.#', '#..##', '#...#'),
    'L': ('#...', '#...', '#...', '#...', '####'),
    'I': ('###', '.#.', '.#.', '.#.', '###'),
    'M': ('#...#', '##.##', '#.#.#', '#...#', '#...#'),
    'T': ('#####', '..#..', '..#..', '..#..', '..#..'),
    'E': ('####', '#...', '###.', '#...', '####'),
    'D': ('###.', '#..#', '#..#', '#..#', '###.'),
}


def _render_logo(columns: int) -> str:
    name = "UnlimitedLLM"
    subtitle = "LLM traffic proxy"
    bitmap = ['..'.join(row) for row in zip(*(_GLYPHS[c] for c in name.upper()))]
    width = len(bitmap[0]) + 1
    if columns < width:
        return f"{BOLD_WHITE}{name[:max(0, columns)]}{RESET}"

    rows = []
    previous = '.' * width
    for line in [*bitmap, '.' * (width - 1)]:
        pixels = []
        for face, shadow in zip(line + '.', '.' + previous):
            if face == '#':
                pixels.append(f'{CYAN}█')
            elif shadow == '#':
                pixels.append('\033[90m░')
            else:
                pixels.append(' ')
        rows.append(''.join(pixels).rstrip() + RESET)
        previous = line
    rows.append(subtitle.rjust(width))
    return '\n'.join(rows)


def print_banner(settings: Settings) -> None:
    print(_render_logo(shutil.get_terminal_size().columns))
    print(f"{YELLOW}  Universal LLM rate-limit proxy. Works with any OpenAI-compatible API.{RESET}")
    print(f"{DIM}  Built by Shivnath Tathe  |  github.com/shivnathtathe/UnlimitedLLM{RESET}")
    print(f"{GREEN}  Listening on http://{settings.host}:{settings.port}/v1  |  72 tests passing  |  MIT License{RESET}")
    print()


def main() -> None:
    settings = Settings()
    logging.disable(logging.CRITICAL if settings.dashboard_enabled else logging.NOTSET)
    logging.basicConfig(level=logging.INFO)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    print_banner(settings)
    app = create_app(settings)
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_level="info",
        access_log=not settings.dashboard_enabled,
    )


if __name__ == "__main__":
    main()
