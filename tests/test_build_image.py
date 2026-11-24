"""scripts/build-image.sh and the optional git hooks (.githooks/).

Every test runs in a throwaway git repository with the real script and hooks
copied in, and stand-ins for `scripts/dev` (the dev image) and `scripts/check`.
Nothing here touches the real work/, firmware/ or a synth.
"""
import hashlib
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

FAKE_DEV = r"""#!/usr/bin/env bash
# Stand-in for scripts/dev (tests/test_build_image.py).
root="$(cd "$(dirname "$0")/.." && pwd)"
[[ "$1" == --image ]] && { echo "fake-dev:${FAKE_IMAGE_TAG:-1}"; exit 0; }
echo "dev $*" >> "$root/calls.log"
if [[ "$1 $2 $3" == "python -I tools/patch.py" ]]; then
    [[ "${FAKE_BUILD_RC:-0}" == 0 ]] || { echo "error: fake build failure" >&2; exit "$FAKE_BUILD_RC"; }
    mkdir -p work/patched
    printf 'image %s' "${FAKE_IMAGE:-one}" > work/patched/fw+mpe.syx
    sha="$(shasum -a 256 < work/patched/fw+mpe.syx | cut -d' ' -f1)"
    [[ -z "${FAKE_BAD_SHA:-}" ]] || sha="0000$sha"
    echo "source  fw.syx  (12 bytes, header 00)"
    echo "verify  ok"
    echo "wrote   $PWD/work/patched/fw+mpe.syx"
    echo "sha256  $sha"
    exit 0
fi
echo "fake dev: unexpected arguments: $*" >&2
exit 3
"""

FAKE_CHECK = r"""#!/usr/bin/env bash
root="$(cd "$(dirname "$0")/.." && pwd)"
echo "check $*" >> "$root/calls.log"
exit "${FAKE_CHECK_RC:-0}"
"""


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Repo:
    def __init__(self, root: Path):
        self.root = root
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        self.env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)

    def run(self, *cmd, check=True, env=None):
        r = subprocess.run(cmd, cwd=self.root, env=dict(self.env, **(env or {})),
                           capture_output=True, text=True)
        if check and r.returncode:
            raise AssertionError(f"{cmd} failed ({r.returncode}):\n{r.stdout}\n{r.stderr}")
        return r

    def git(self, *args, **kw):
        return self.run("git", *args, **kw)

    def build(self, *args, **env):
        return self.run("scripts/build-image.sh", *args, check=False, env=env)

    def calls(self):
        p = self.root / "calls.log"
        return p.read_text() if p.exists() else ""


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "work tree"  # a space, as paths on a Mac often have
    root.mkdir()
    r = Repo(root)
    r.git("init", "-q", "-b", "main")
    for k, v in [("user.name", "Test"), ("user.email", "test@example.invalid"), ("commit.gpgSign", "false")]:
        r.git("config", k, v)
    (root / "scripts").mkdir()
    for name in ("build-image.sh", "check-key"):
        shutil.copy2(REPO / "scripts" / name, root / "scripts" / name)
        (root / "scripts" / name).chmod(0o755)
    for name, text in (("dev", FAKE_DEV), ("check", FAKE_CHECK)):
        (root / "scripts" / name).write_text(text)
        (root / "scripts" / name).chmod(0o755)
    shutil.copytree(REPO / ".githooks", root / ".githooks")
    (root / ".gitignore").write_text("/work/\n/firmware/*\n!/firmware/README.md\ncalls.log\n")
    (root / "patches" / "mpe").mkdir(parents=True)
    (root / "patches" / "mpe" / "patch.py").write_text("# placeholder\n")
    (root / "firmware").mkdir()
    (root / "firmware" / "README.md").write_text("readme\n")
    (root / "firmware" / "summit-firmware-2.2-build2121.syx").write_text("fake stock\n")
    r.git("add", "-A")
    r.git("commit", "-q", "-m", "base")
    r.git("config", "core.hooksPath", ".githooks")
    return r


def test_build_runs_the_checks_and_prints_the_flash_commands(repo):
    r = repo.build()
    assert r.returncode == 0, r.stderr
    digest = sha(b"image one")
    flashfile = f"work/flash/fw+mpe-{digest[:12]}.syx"
    assert (repo.root / flashfile).read_bytes() == b"image one"
    assert repo.calls().splitlines() == [
        "check ", "dev python -I tools/patch.py patches/mpe/patch.py --verify"]
    out = r.stdout
    assert digest in out
    assert f'cd "{repo.root}"' in out
    # Recovery first, then check, dry run and the real flash, all on the copy.
    assert out.index("Recovery") < out.index("tools/flash.py check")
    assert f".venv/bin/python -I tools/flash.py flash firmware/fw.syx" in out
    assert f"tools/flash.py check {flashfile}" in out
    assert f"tools/flash.py flash {flashfile} --dry-run" in out
    assert f"--log work/flash-{digest[:8]}-$(date +%F).log" in out
    assert "uncommitted" not in out


def test_a_later_build_does_not_overwrite_the_copy(repo):
    assert repo.build("--skip-checks").returncode == 0
    assert repo.build("--skip-checks", FAKE_IMAGE="two").returncode == 0
    names = sorted(p.name for p in (repo.root / "work" / "flash").iterdir())
    assert names == sorted(f"fw+mpe-{sha(b'image ' + w)[:12]}.syx" for w in (b"one", b"two"))
    assert "check" not in repo.calls()


def test_failing_checks_build_nothing(repo):
    r = repo.build(FAKE_CHECK_RC="1")
    assert r.returncode != 0 and "scripts/check failed" in r.stderr
    assert "tools/patch.py" not in repo.calls()


@pytest.mark.parametrize("env, message", [
    ({"FAKE_BUILD_RC": "2"}, "build failed"),
    ({"FAKE_BAD_SHA": "1"}, "the build printed"),
])
def test_a_bad_build_prints_no_flash_commands(repo, env, message):
    r = repo.build("--skip-checks", **env)
    assert r.returncode != 0 and message in r.stderr
    assert "tools/flash.py" not in r.stdout


def test_build_names_uncommitted_changes(repo):
    (repo.root / "patches" / "mpe" / "patch.py").write_text("# changed\n")
    r = repo.build("--skip-checks")
    assert r.returncode == 0 and "plus uncommitted changes" in r.stdout


def test_build_needs_the_firmware(repo):
    (repo.root / "firmware" / "summit-firmware-2.2-build2121.syx").unlink()
    r = repo.build()
    assert r.returncode != 0 and "fetch-firmware.sh" in r.stderr
    assert repo.calls() == ""


def test_pre_commit_refuses_firmware_and_generated_files(repo):
    for path in ("stray.syx", "work/out.txt", "firmware/other.txt"):
        f = repo.root / path
        f.parent.mkdir(exist_ok=True)
        f.write_text("x\n")
        repo.git("add", "-f", path)
        r = repo.git("commit", "-q", "-m", "bad", check=False)
        assert r.returncode != 0 and "never commit these" in r.stderr, path
        repo.git("rm", "-q", "--cached", path)
    (repo.root / "ok.txt").write_text("fine\n")
    repo.git("add", "ok.txt")
    repo.git("commit", "-q", "-m", "fine")


def test_pre_push_refuses_a_commit_that_adds_firmware(repo, tmp_path):
    remote = tmp_path / "remote.git"
    repo.run("git", "init", "-q", "--bare", str(remote))
    repo.git("remote", "add", "origin", str(remote))
    repo.git("push", "-q", "origin", "main")
    (repo.root / "stray.syx").write_text("x\n")
    repo.git("add", "-f", "stray.syx")
    repo.git("-c", "core.hooksPath=/dev/null", "commit", "-q", "-m", "bypassed the pre-commit hook")
    r = repo.git("push", "origin", "main", check=False)
    assert r.returncode != 0 and "stray.syx" in r.stderr


def _stamp(repo):
    key = repo.run("scripts/check-key").stdout.strip()
    assert len(key) == 64
    (repo.root / "work").mkdir(exist_ok=True)
    (repo.root / "work" / "check-stamp").write_text(f"key {key}\npassed 2026-11-20 09:00 MST\ncommit abc\n")
    return key


def test_a_check_that_passed_on_the_same_inputs_is_reused(repo):
    _stamp(repo)
    r = repo.build()
    assert r.returncode == 0, r.stderr
    assert "check " not in repo.calls()
    assert "scripts/check: reused" in r.stdout and "2026-11-20 09:00" in r.stdout


def test_a_docs_only_change_keeps_the_stamp_and_a_code_change_does_not(repo):
    _stamp(repo)
    (repo.root / "docs").mkdir()
    (repo.root / "docs" / "notes.md").write_text("only words\n")
    (repo.root / "README.md").write_text("more words\n")
    assert repo.build().returncode == 0
    assert "check " not in repo.calls()
    (repo.root / "patches" / "mpe" / "patch.py").write_text("# changed\n")
    assert repo.build().returncode == 0
    assert repo.calls().count("check ") == 1


@pytest.mark.parametrize("change", ["untracked", "firmware", "image", "recheck"])
def test_what_makes_the_check_run_again(repo, change):
    _stamp(repo)
    args, env = [], {}
    if change == "untracked":
        (repo.root / "tools.py").write_text("new\n")                      # not ignored: in the key
    elif change == "firmware":
        (repo.root / "firmware" / "summit-firmware-2.2-build2121.syx").write_text("other stock\n")
    elif change == "image":
        env["FAKE_IMAGE_TAG"] = "2"
    else:
        args.append("--recheck")
    assert repo.build(*args, **env).returncode == 0
    assert repo.calls().count("check ") == 1


def test_ignored_files_are_not_in_the_key(repo):
    key = repo.run("scripts/check-key").stdout.strip()
    (repo.root / "work").mkdir(exist_ok=True)
    (repo.root / "work" / "scratch.txt").write_text("x\n")
    (repo.root / "calls.log").write_text("x\n")
    assert repo.run("scripts/check-key").stdout.strip() == key
