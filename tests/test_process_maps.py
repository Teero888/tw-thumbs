import contextlib
import importlib.util
import io
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "process_maps", PROJECT_ROOT / "scripts" / "process_maps.py"
)
process_maps = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(process_maps)


def git(*args, cwd):
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def configure_git(repo):
    git("config", "user.name", "Test User", cwd=repo)
    git("config", "user.email", "test@example.invalid", cwd=repo)


class ChangedMapPathsTests(unittest.TestCase):
    def test_only_returns_changed_map_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            git("init", "--initial-branch=master", cwd=repo)
            configure_git(repo)

            maps_dir = repo / "maps"
            maps_dir.mkdir()
            (maps_dir / "modified.map").write_text("version 1")
            (maps_dir / "deleted.map").write_text("delete me")
            (repo / "votes.cfg").write_text("version 1")
            git("add", ".", cwd=repo)
            git("commit", "-m", "initial", cwd=repo)
            previous_sha = process_maps.get_git_head_sha(repo)

            (maps_dir / "modified.map").write_text("version 2")
            (maps_dir / "deleted.map").unlink()
            (maps_dir / "added.map").write_text("new")
            (repo / "votes.cfg").write_text("version 2")
            git("add", "-A", cwd=repo)
            git("commit", "-m", "update", cwd=repo)
            current_sha = process_maps.get_git_head_sha(repo)

            changed = process_maps.get_changed_map_paths(
                repo, previous_sha, current_sha
            )

            self.assertEqual(
                changed,
                {
                    "maps/added.map",
                    "maps/deleted.map",
                    "maps/modified.map",
                },
            )

    def test_fetches_previous_commit_for_a_fresh_shallow_clone(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            remote = temp_path / "remote.git"
            source = temp_path / "source"
            shallow = temp_path / "shallow"

            git("init", "--bare", "--initial-branch=master", str(remote), cwd=temp_path)
            git("clone", str(remote), str(source), cwd=temp_path)
            configure_git(source)

            source_map = source / "maps" / "example.map"
            source_map.parent.mkdir()
            source_map.write_text("version 1")
            git("add", ".", cwd=source)
            git("commit", "-m", "initial", cwd=source)
            git("push", "origin", "master", cwd=source)
            previous_sha = process_maps.get_git_head_sha(source)

            source_map.write_text("version 2")
            git("add", ".", cwd=source)
            git("commit", "-m", "update", cwd=source)
            git("push", "origin", "master", cwd=source)
            current_sha = process_maps.get_git_head_sha(source)

            git(
                "clone",
                "--depth",
                "1",
                remote.as_uri(),
                str(shallow),
                cwd=temp_path,
            )
            self.assertNotEqual(
                process_maps.run_cmd(
                    ["git", "cat-file", "-e", f"{previous_sha}^{{commit}}"],
                    cwd=shallow,
                ).returncode,
                0,
            )

            changed = process_maps.get_changed_map_paths(
                shallow, previous_sha, current_sha
            )

            self.assertEqual(changed, {"maps/example.map"})


class RenderDiagnosticsTests(unittest.TestCase):
    def test_renderer_stderr_is_printed_when_no_thumbnail_is_created(self):
        result = subprocess.CompletedProcess(
            args=["twgpu"], returncode=7, stdout="", stderr="unsupported layer"
        )

        with tempfile.TemporaryDirectory() as work_dir:
            output = io.StringIO()
            with mock.patch.object(process_maps, "run_cmd", return_value=result):
                with contextlib.redirect_stdout(output):
                    generated = process_maps.render_with_twgpu(
                        Path("/bin/twgpu"),
                        Path("/tmp/example.map"),
                        work_dir,
                        "1280x720",
                        "example",
                    )

        self.assertIsNone(generated)
        self.assertIn("code 7", output.getvalue())
        self.assertIn("unsupported layer", output.getvalue())


class ExistingManifestTests(unittest.TestCase):
    def test_targeted_runs_can_preserve_unprocessed_repositories(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "maps.json").write_text(
                """
                {
                  "maps": {
                    "ddnet": [{"name": "ddnet map"}],
                    "unique": [{"name": "unique map"}],
                    "unknown": [{"name": "ignore me"}]
                  }
                }
                """
            )

            existing = process_maps.load_existing_repo_map_data(root)

        self.assertEqual(
            existing,
            {
                "ddnet": [{"name": "ddnet map"}],
                "unique": [{"name": "unique map"}],
            },
        )


class ProcessRepoTests(unittest.TestCase):
    def test_changed_existing_map_failure_does_not_advance_state_or_manifest(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            remote = temp_path / "remote.git"
            source = temp_path / "source"
            root = temp_path / "project"
            clone = root / "tmp_repos" / "ddnet"

            git("init", "--bare", "--initial-branch=master", str(remote), cwd=temp_path)
            git("clone", str(remote), str(source), cwd=temp_path)
            configure_git(source)

            source_map = source / "types" / "solo" / "maps" / "example.map"
            source_map.parent.mkdir(parents=True)
            source_map.write_text("version 1")
            git("add", ".", cwd=source)
            git("commit", "-m", "initial", cwd=source)
            git("push", "origin", "master", cwd=source)
            previous_sha = process_maps.get_git_head_sha(source)

            clone.parent.mkdir(parents=True)
            git("clone", str(remote), str(clone), cwd=temp_path)

            thumbnail_dir = root / "ddnet"
            thumbnail_dir.mkdir(parents=True)
            (thumbnail_dir / "example.png").write_bytes(b"old thumbnail")

            source_map.write_text("version 2")
            git("add", ".", cwd=source)
            git("commit", "-m", "modify map", cwd=source)
            git("push", "origin", "master", cwd=source)

            state = {"ddnet": previous_sha}
            repo_map_data = {}
            args = SimpleNamespace(force=False, jobs=1, resolution="1280x720")

            with mock.patch.object(
                process_maps, "fetch_ddnet_metadata", return_value={}
            ):
                with mock.patch.object(
                    process_maps, "render_single_map", return_value=False
                ) as render:
                    failed_count = process_maps.process_repo(
                        "ddnet",
                        {"url": str(remote), "dir": "ddnet"},
                        args,
                        root,
                        Path("/bin/twgpu"),
                        Path("/bin/twmap"),
                        state,
                        repo_map_data,
                    )

            self.assertEqual(failed_count, 1)
            render.assert_called_once()
            self.assertEqual(state["ddnet"], previous_sha)
            self.assertEqual(repo_map_data["ddnet"], [])


if __name__ == "__main__":
    unittest.main()
