# tw-thumbs

Automated Teeworlds & DDNet map thumbnail renderer powered by GitHub Workflows, [`twgpu-map-photography`](https://gitlab.com/ddnet-rs/twgpu), and [`twmap-fix`](https://gitlab.com/ddnet-rs/twmap).

## Repositories & Thumbnail Directories

Thumbnails are automatically generated from `.map` files in the following repositories and placed into corresponding subdirectories mirroring each map's path:

| Map Repository | Target Directory |
|---|---|
| [`https://github.com/ddnet/ddnet-maps`](https://github.com/ddnet/ddnet-maps) | `ddnet/` |
| [`https://github.com/unique-clan/unique-maps`](https://github.com/unique-clan/unique-maps) | `unique/` |
| [`https://github.com/Gamer12120/KoGmaps`](https://github.com/Gamer12120/KoGmaps) | `kog/` |

## Resolution & Rendering Process

1. Maps are rendered at **1280x720** resolution using `twgpu-map-photography`:
   ```bash
   twgpu-map-photography <map_path> -r 1280x720
   ```
2. If `twgpu-map-photography` fails on corrupt or non-standard maps, the map is automatically fixed using `twmap-fix`:
   ```bash
   twmap-fix <map_path> <fixed_map_path>
   ```
   and re-rendered with `twgpu-map-photography`.
3. Rendered `.png` thumbnails are saved under their respective category directories (`ddnet/`, `unique/`, `kog/`) preserving the relative subdirectory hierarchy of each map repository.

## GitHub Workflows Automation

The GitHub Workflow (`.github/workflows/generate_thumbnails.yml`) runs automatically:
- **Scheduled Cron**: Checks every 3 hours for new commits on any of the 3 map repositories.
- **Repository Dispatch**: Responds to `repository_dispatch` webhooks (`map_updated`, `ddnet_updated`, `unique_updated`, `kog_updated`, `generate_thumbnails`).
- **Manual Trigger**: Can be manually triggered from GitHub's **Actions** tab with options for specific target repos or forced re-rendering.

## Running Locally

To render thumbnails locally:

1. **Build Tools**:
   ```bash
   ./scripts/build_tools.sh
   ```
2. **Process Maps**:
   ```bash
   python3 scripts/process_maps.py --target all --resolution 1280x720 --jobs 4
   ```

### Command Line Options

- `--target`: Repository to process (`all`, `ddnet`, `unique`, `kog`).
- `--resolution`: Image dimensions (default: `1280x720`).
- `--force`: Re-render existing thumbnails.
- `--jobs`: Number of parallel render workers (default: `4`).
