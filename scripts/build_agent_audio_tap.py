from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ableton_paths import default_user_library, state_dir
from audio_tap import build_tap, max_arg, patch_text

SOURCE_PATCH = ROOT / "m4l" / "AgentAudioTap.maxpat"
DEFAULT_OUTPUT = ROOT / "m4l" / "AgentAudioTap.amxd"


def user_library_device() -> Path:
    return default_user_library() / "Presets" / "Audio Effects" / "Max Audio Effect" / "AgentAudioTap.amxd"


def patch_with_command_file(source: Path, command_file: Path | str) -> str:
    return patch_text(source, command_file)


def build_amxd(source: Path, output: Path, command_file: Path | str | None = None) -> None:
    build_tap(source, output, command_file or state_dir() / "agent_audio_tap_command.json")


def install_companion_files(device_path: Path) -> None:
    js_source = ROOT / "m4l" / "agent_audio_tap.js"
    js_output = device_path.with_name(js_source.name)
    js_output.write_text(js_source.read_text(encoding="utf-8"), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the AgentAudioTap Max for Live audio effect.")
    parser.add_argument("--source", type=Path, default=SOURCE_PATCH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--install", action="store_true", help="Also install into the Ableton User Library.")
    args = parser.parse_args()

    build_amxd(args.source, args.output)
    install_companion_files(args.output)
    print(args.output)

    if args.install:
        installed = user_library_device()
        build_amxd(args.source, installed)
        install_companion_files(installed)
        print(installed)


if __name__ == "__main__":
    main()
