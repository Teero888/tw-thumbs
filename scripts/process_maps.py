#!/usr/bin/env python3
"""
Thumbnail generator for DDNet, Unique, and KoG map repositories using twgpu-map-photography and twmap-fix.
Generates JSON endpoints containing map relative paths, thumbnail paths, and detailed map metadata:
- DDNet: type, difficulty (1-5), points
- Unique: category (fetched from uniqueclan.net, cached in maps.json)
- KoG: difficulty, stars (numeric), points, length (parsed from mapinfo.txt)
Also lists distinct string categories/types at the top of maps.json.
"""

import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
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


def fetch_ddnet_metadata():
    """Fetches DDNet map metadata from bulk release API."""
    metadata = {}
    url = "https://ddnet.org/releases/maps.json"
    print(f"[METADATA] Fetching DDNet map metadata from {url}...")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
        for m in data:
            metadata[m["name"]] = {
                "type": m.get("type"),
                "difficulty": m.get("difficulty"),
                "points": m.get("points"),
            }
        print(f"[METADATA] Successfully loaded metadata for {len(metadata)} DDNet maps.")
    except Exception as e:
        print(f"[METADATA WARNING] Failed to fetch DDNet bulk metadata: {e}")
    return metadata


def fetch_unique_category(map_name, cache):
    """Fetches category for a single Unique map from uniqueclan.net HTML."""
    if map_name in cache and cache[map_name] is not None:
        return cache[map_name]

    url = f"https://uniqueclan.net/map/{map_name}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
        cat_match = re.search(r"Category:\s*([^<]+)", html)
        if cat_match:
            cat = cat_match.group(1).strip()
            cache[map_name] = cat
            return cat
    except Exception:
        pass

    cache[map_name] = None
    return None


def fetch_all_unique_metadata(map_names, root_dir):
    """Fetches categories for Unique maps using existing maps.json for caching."""
    cache = {}
    maps_json_path = root_dir / "maps.json"

    if maps_json_path.exists():
        try:
            with open(maps_json_path, "r") as f:
                existing_data = json.load(f)

            if isinstance(existing_data, dict) and "maps" in existing_data and "unique" in existing_data["maps"]:
                for entry in existing_data["maps"]["unique"]:
                    if isinstance(entry, dict) and "name" in entry and "category" in entry:
                        if entry["category"] is not None:
                            cache[entry["name"]] = entry["category"]
        except Exception:
            cache = {}

    print(f"[METADATA] Checking Unique map categories ({len(map_names)} maps)...")
    missing_maps = [m for m in map_names if m not in cache or cache[m] is None]

    if missing_maps:
        print(f"[METADATA] Fetching {len(missing_maps)} uncached Unique map categories from uniqueclan.net...")
        with ThreadPoolExecutor(max_workers=16) as executor:
            futures = [executor.submit(fetch_unique_category, m, cache) for m in missing_maps]
            for future in as_completed(futures):
                pass

    print(f"[METADATA] Successfully loaded metadata for {len(cache)} Unique maps.")
    return cache


def parse_kog_metadata(clone_dir):
    """Parses KoG mapinfo.txt file for difficulty, stars, points, and length."""
    metadata = {}
    mapinfo_path = clone_dir / "mapinfo.txt"

    if not mapinfo_path.exists():
        url = "https://raw.githubusercontent.com/Gamer12120/KoGmaps/refs/heads/main/mapinfo.txt"
        print(f"[METADATA] Fetching KoG mapinfo.txt from {url}...")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                content = resp.read().decode("utf-8", errors="ignore")
            lines = content.splitlines()
        except Exception as e:
            print(f"[METADATA WARNING] Failed to fetch KoG mapinfo.txt: {e}")
            return metadata
    else:
        with open(mapinfo_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()

    for line in lines[2:]:
        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 5:
            map_name = parts[0]
            if not map_name or map_name.startswith("="):
                continue
            diff = parts[1]
            stars = parts[2].count("★")
            pts = int(parts[3]) if parts[3].isdigit() else None
            length = parts[4]

            metadata[map_name] = {
                "difficulty": diff,
                "stars": stars,
                "points": pts,
                "length": length,
            }

    print(f"[METADATA] Successfully loaded metadata for {len(metadata)} KoG maps.")
    return metadata


def render_with_twgpu(twgpu_bin, map_path, work_dir, resolution, stem):
    """Helper to run twgpu and look for any variation of the generated image."""
    cmd = [str(twgpu_bin), str(map_path), "-r", resolution]
    run_cmd(cmd, cwd=work_dir)
    
    patterns = [f"{stem}_{resolution}.png", f"{stem}.png", f"{stem}_fixed_{resolution}.png", f"{stem}_fixed.png"]
    for pattern in patterns:
        img_path = Path(work_dir) / pattern
        if img_path.exists():
            return img_path
    return None


def render_single_map(map_path, output_png_path, twgpu_bin, twmap_bin, resolution):
    output_png_path = Path(output_png_path)
    output_png_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as work_dir:
        work_path = Path(work_dir)
        map_path_abs = Path(map_path).resolve()
        map_stem = map_path_abs.stem

        # Try 1: Direct render
        generated_png = render_with_twgpu(twgpu_bin, map_path_abs, work_dir, resolution, map_stem)

        # Try 2: Fix once and retry once if Try 1 failed
        if not generated_png:
            print(f"[FIX] Direct render failed for {map_path_abs.name}. Attempting twmap-fix...")
            fixed_map_path = work_path / f"{map_stem}_fixed.map"
            fix_cmd = [str(twmap_bin), str(map_path_abs), str(fixed_map_path)]
            fix_res = run_cmd(fix_cmd, cwd=work_dir)

            if fix_res.returncode == 0 and fixed_map_path.exists():
                print(f"[RETRY] Retrying render on fixed map for {map_path_abs.name}...")
                generated_png = render_with_twgpu(twgpu_bin, fixed_map_path, work_dir, resolution, map_stem)

        # Save result if successful
        if generated_png and generated_png.exists():
            shutil.copy2(generated_png, output_png_path)
            print(f"[SUCCESS] Rendered {map_path_abs.name} -> {output_png_path}")
            return True
        else:
            print(f"[ERROR] Failed to render thumbnail for {map_path_abs.name}")
            return False


def process_repo(repo_name, config, args, root_dir, twgpu_bin, twmap_bin, state, repo_map_data):
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

    map_files = sorted(list(clone_dir.glob("**/*.map")))

    # Completely ignore duplicate maps7 directory in unique-maps repo
    if repo_name == "unique":
        map_files = [m for m in map_files if "maps7" not in m.relative_to(clone_dir).parts]

    print(f"Found {len(map_files)} map files in {repo_name}.")

    # Load repo-specific metadata
    meta_dict = {}
    if repo_name == "ddnet":
        meta_dict = fetch_ddnet_metadata()
    elif repo_name == "unique":
        map_stems = [m.stem for m in map_files]
        meta_dict = fetch_all_unique_metadata(map_stems, root_dir)
    elif repo_name == "kog":
        meta_dict = parse_kog_metadata(clone_dir)

    # Collect map repository relative paths and metadata
    map_list = []
    for map_file in map_files:
        stem = map_file.stem
        rel_map_path = str(map_file.relative_to(clone_dir))
        thumb_path = f"{repo_name}/{stem}.png"

        item = {
            "name": stem,
            "repo": repo_name,
            "map_path": rel_map_path,
            "thumbnail_path": thumb_path,
        }

        # Inject repository-specific metadata
        if repo_name == "ddnet":
            m_info = meta_dict.get(stem, {})
            item["type"] = m_info.get("type")
            item["difficulty"] = m_info.get("difficulty")
            item["points"] = m_info.get("points")
        elif repo_name == "unique":
            item["category"] = meta_dict.get(stem)
        elif repo_name == "kog":
            m_info = meta_dict.get(stem, {})
            item["difficulty"] = m_info.get("difficulty")
            item["stars"] = m_info.get("stars")
            item["points"] = m_info.get("points")
            item["length"] = m_info.get("length")

        map_list.append(item)

    repo_map_data[repo_name] = map_list

    rendered_count = 0
    skipped_count = 0
    failed_count = 0

    tasks = []
    with ThreadPoolExecutor(max_workers=args.jobs) as executor:
        for map_file in map_files:
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


def build_api_manifest(root_dir, resolution, repo_map_data):
    """Generates maps.json and api/maps.json JSON endpoints including type lists at top."""
    api_dir = root_dir / "api"
    api_dir.mkdir(parents=True, exist_ok=True)

    # Collect distinct string types/categories per repo
    ddnet_types = sorted(list(set(m.get("type") for m in repo_map_data.get("ddnet", []) if m.get("type"))))
    unique_categories = sorted(list(set(m.get("category") for m in repo_map_data.get("unique", []) if m.get("category"))))
    kog_difficulties = sorted(list(set(m.get("difficulty") for m in repo_map_data.get("kog", []) if m.get("difficulty"))))

    manifest = {
        "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "resolution": resolution,
        "types": {
            "ddnet": ddnet_types,
            "unique": unique_categories,
            "kog": kog_difficulties,
        },
        "counts": {},
        "maps": {},
    }

    flat_list = []
    total = 0

    for repo in ["ddnet", "unique", "kog"]:
        map_entries = repo_map_data.get(repo, [])
        manifest["counts"][repo] = len(map_entries)
        manifest["maps"][repo] = map_entries
        total += len(map_entries)
        flat_list.extend(map_entries)

    manifest["counts"]["total"] = total

    # Write root maps.json
    with open(root_dir / "maps.json", "w") as f:
        json.dump(manifest, f, indent=2)

    # Write api/maps.json
    with open(api_dir / "maps.json", "w") as f:
        json.dump(flat_list, f, indent=2)

    print(f"\n[API] Manifest generated: {total} map paths indexed in maps.json and api/maps.json.")


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

    repo_map_data = {}
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
                repo_map_data,
            )

    with open(state_path, "w") as f:
        json.dump(state, f, indent=2)

    build_api_manifest(root_dir, args.resolution, repo_map_data)

    print("\nAll map processing finished.")


if __name__ == "__main__":
    main()