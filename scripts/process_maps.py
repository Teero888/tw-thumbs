#!/usr/bin/env python3
"""
Thumbnail generator for DDNet, Unique, and KoG map repositories using twgpu-map-photography and twmap-fix.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REPOS = {
    "ddnet": {
        "url": "https://github.com/ddnet/ddnet-maps.git",
        "dir": "ddnet",
    },
    "unique": {
        "url": "https://github.com/unique-clan/unique-maps.git",
        "dir": "unique",
    },
    "kog": {
        "url": "https://github.com/Gamer12120/KoGmaps.git",
        "dir": "kog",
    },
}

DEFAULT_TWGPU_BIN = "twgpu/target/release/twgpu-map-photography"
DEFAULT_TWMAP_BIN = "twmap/target/release/twmap-fix"
STATE_FILE = ".commit_hashes.json"


def run_cmd(cmd, cwd=None, check=False):
    res = subprocess.run(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if check and res.returncode != 0:
        raise RuntimeError(f"Command {' '.join(cmd)} failed (code {res.returncode}):\n{res.stderr}")
    return res


def get_git_head_sha(repo_dir):
    res = run_cmd(["git", "rev-parse", "HEAD"], cwd=repo_dir)
    if res.returncode == 0:
        return res.stdout.strip()
    return None


def render_single_map(map_path, output_png_path, twgpu_bin, twmap_bin, resolution):
    """
    Renders a single map using twgpu-map-photography, falling back to twmap-fix if needed.
    """
    output_png_path = Path(output_png_path)
    output_png_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as work_dir:
        work_path = Path(work_dir)
        map_path_abs = Path(map_path).resolve()
        map_stem = map_path_abs.stem

        # Step 1: Try rendering directly with twgpu-map-photography
        # Command format: twgpu-map-photography <map_path> -r <resolution>
        cmd = [str(twgpu_bin), str(map_path_abs), "-r", resolution]
        res = run_cmd(cmd, cwd=work_dir)

        # twgpu-map-photography outputs mapstem_1280x720.png or mapstem.png
        generated_png = work_path / f"{map_stem}_{resolution}.png"
        if not generated_png.exists():
            generated_png = work_path / f"{map_stem}.png"

        # Step 2: If rendering failed or PNG was not produced, try twmap-fix
        if res.returncode != 0 or not generated_png.exists():
            print(f"[FIX] Direct render failed for {map_path_abs.name}, trying twmap-fix...")
            fixed_map_path = work_path / f"{map_stem}_fixed.map"
            fix_cmd = [str(twmap_bin), str(map_path_abs), str(fixed_map_path)]
            fix_res = run_cmd(fix_cmd, cwd=work_dir)

            if fix_res.returncode == 0 and fixed_map_path.exists():
                print(f"[RETRY] Retrying twgpu-map-photography on fixed map for {map_path_abs.name}...")
                retry_cmd = [str(twgpu_bin), str(fixed_map_path), "-r", resolution]
                retry_res = run_cmd(retry_cmd, cwd=work_dir)

                generated_png = work_path / f"{map_stem}_fixed_{resolution}.png"
                if not generated_png.exists():
                    generated_png = work_path / f"{map_stem}_fixed.png"
                if not generated_png.exists():
                    generated_png = work_path / f"{map_stem}_{resolution}.png"
                if not generated_png.exists():
                    generated_png = work_path / f"{map_stem}.png"

        # Step 3: If PNG was created, move it to the output destination
        if generated_png.exists():
            shutil.copy2(generated_png, output_png_path)
            print(f"[SUCCESS] Rendered {map_path_abs.name} -> {output_png_path}")
            return True
        else:
            print(f"[ERROR] Failed to render thumbnail for {map_path_abs.name}")
            return False


def process_repo(repo_name, config, args, root_dir, twgpu_bin, twmap_bin, state):
    target_dir = root_dir / config["dir"]
    target_dir.mkdir(parents=True, exist_ok=True)

    clone_dir = root_dir / "tmp_repos" / repo_name
    print(f"\n==========================================")
    print(f"Processing repository: {repo_name} ({config['url']})")
    print(f"==========================================")

    if clone_dir.exists():
        print(f"Updating repository {repo_name}...")
        run_cmd(["git", "fetch", "--all"], cwd=clone_dir)
        run_cmd(["git", "reset", "--hard", "origin/HEAD"], cwd=clone_dir)
    else:
        print(f"Cloning repository {repo_name}...")
        clone_dir.parent.mkdir(parents=True, exist_ok=True)
        run_cmd(["git", "clone", "--depth", "1", config["url"], str(clone_dir)], check=True)

    current_sha = get_git_head_sha(clone_dir)
    print(f"Current HEAD commit SHA for {repo_name}: {current_sha}")

    # Find all .map files in the repo
    map_files = sorted(list(clone_dir.glob("**/*.map")))
    print(f"Found {len(map_files)} map files in {repo_name}.")

    rendered_count = 0
    skipped_count = 0
    failed_count = 0

    tasks = []
    with ThreadPoolExecutor(max_workers=args.jobs) as executor:
        for map_file in map_files:
            # Flatten path: force output to be immediately under target_dir as <mapname>.png
            output_png_path = target_dir / f"{map_file.stem}.png"

            if output_png_path.exists() and not args.force:
                skipped_count += 1
                continue

            tasks.append(
                executor.submit(
                    render_single_map,
                    map_file,
                    output_png_path,
                    twgpu_bin,
                    twmap_bin,
                    args.resolution,
                )
            )

        for future in as_completed(tasks):
            try:
                success = future.result()
                if success:
                    rendered_count += 1
                else:
                    failed_count += 1
            except Exception as e:
                print(f"[EXCEPTION] Error during rendering: {e}")
                failed_count += 1

    print(f"Summary for {repo_name}: Rendered: {rendered_count}, Skipped: {skipped_count}, Failed: {failed_count}")
    if current_sha:
        state[repo_name] = current_sha


def main():
    parser = argparse.ArgumentParser(description="Generate map thumbnails for Teeworlds/DDNet maps.")
    parser.add_argument(
        "--twgpu-bin",
        default=DEFAULT_TWGPU_BIN,
        help="Path to twgpu-map-photography binary",
    )
    parser.add_argument(
        "--twmap-bin",
        default=DEFAULT_TWMAP_BIN,
        help="Path to twmap-fix binary",
    )
    parser.add_argument(
        "--resolution",
        default="1280x720",
        help="Thumbnail resolution (widthxheight), default: 1280x720",
    )
    parser.add_argument(
        "--target",
        choices=["all", "ddnet", "unique", "kog"],
        default="all",
        help="Target map repository to process",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-rendering existing thumbnails",
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=4,
        help="Number of concurrent rendering jobs",
    )

    args = parser.parse_args()

    root_dir = Path(__file__).resolve().parent.parent
    twgpu_bin = root_dir / args.twgpu_bin if not Path(args.twgpu_bin).is_absolute() else Path(args.twgpu_bin)
    twmap_bin = root_dir / args.twmap_bin if not Path(args.twmap_bin).is_absolute() else Path(args.twmap_bin)

    if not twgpu_bin.exists() and (root_dir / "bin" / "twgpu-map-photography").exists():
        twgpu_bin = root_dir / "bin" / "twgpu-map-photography"
    if not twmap_bin.exists() and (root_dir / "bin" / "twmap-fix").exists():
        twmap_bin = root_dir / "bin" / "twmap-fix"

    if not twgpu_bin.exists():
        print(f"Error: twgpu-map-photography binary not found at {twgpu_bin}. Run scripts/build_tools.sh first.")
        sys.exit(1)
    if not twmap_bin.exists():
        print(f"Error: twmap-fix binary not found at {twmap_bin}. Run scripts/build_tools.sh first.")
        sys.exit(1)

    print(f"Using twgpu-map-photography: {twgpu_bin}")
    print(f"Using twmap-fix: {twmap_bin}")
    print(f"Resolution: {args.resolution}")

    state_path = root_dir / STATE_FILE
    state = {}
    if state_path.exists():
        try:
            with open(state_path, "r") as f:
                state = json.load(f)
        except Exception:
            state = {}

    targets = [args.target] if args.target != "all" else ["ddnet", "unique", "kog"]
    for repo_name in targets:
        if repo_name in REPOS:
            process_repo(
                repo_name,
                REPOS[repo_name],
                args,
                root_dir,
                twgpu_bin,
                twmap_bin,
                state,
            )

    with open(state_path, "w") as f:
        json.dump(state, f, indent=2)

    print("\nAll map processing finished.")


if __name__ == "__main__":
    main()