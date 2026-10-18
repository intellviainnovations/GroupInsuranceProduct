"""QA tests for T-006 fix R7: ``scripts/check_repo.sh`` secret tripwire.

Each test builds a throwaway git repository under pytest's temp directory (outside this repo),
copies the script into it, creates files and runs ``bash scripts/check_repo.sh``. Sample secrets
are assembled at runtime from fragments, so this file itself contains no secret-shaped literal and
the repo's own scan stays clean. Everything is synthetic.

Skipped, with a reason, if no usable bash with git and grep is found. On Windows the bash of Git
for Windows is used (the WSL launcher ``bash.exe`` in System32 is deliberately not used).
"""

# ruff: noqa: S603, S607  (running bash/git in a scratch repo is the point of these tests)

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "check_repo.sh"


def _find_bash() -> str | None:
    candidates: list[str] = []
    if os.name == "nt":
        roots: list[Path] = []
        git = shutil.which("git")
        if git:
            roots += list(Path(git).resolve().parents)[:4]
        for variable in ("ProgramFiles", "ProgramW6432", "LocalAppData"):
            if os.environ.get(variable):
                roots.append(Path(os.environ[variable]) / "Git")
        for root in roots:
            candidates += [str(root / "bin" / "bash.exe"), str(root / "usr" / "bin" / "bash.exe")]
    else:
        found = shutil.which("bash")
        if found:
            candidates.append(found)
    for candidate in candidates:
        if not Path(candidate).exists():
            continue
        probe = subprocess.run(
            [candidate, "-c", "command -v git >/dev/null && command -v grep >/dev/null && echo ok"],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        if probe.returncode == 0 and probe.stdout.strip() == "ok":
            return candidate
    return None


BASH = _find_bash()
pytestmark = pytest.mark.skipif(
    BASH is None, reason="no usable bash (with git and grep) found on this host"
)

PW = "pass" + "word"
SAMPLE_CRED = "hunter2"  # synthetic


def _env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    return env


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args], cwd=repo, env=_env(), check=True, capture_output=True, timeout=60
    )


def make_repo(root: Path) -> Path:
    """A minimal repo that satisfies the script's own required-file checks."""
    repo = root / "scratch-repo"
    assert REPO_ROOT not in repo.resolve().parents, "temp repo must live outside this repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / "release").mkdir()
    (repo / "docs" / "templates").mkdir(parents=True)
    # Normalise to LF: a CRLF checkout of the script would not be a fair test of its logic.
    script_text = SCRIPT.read_bytes().replace(b"\r\n", b"\n")
    (repo / "scripts" / "check_repo.sh").write_bytes(script_text)
    for name in ("CLAUDE.md", "README.md", "docs/templates/task-handoff.md"):
        (repo / name).write_text("synthetic\n", encoding="utf-8")
    (repo / "docs/templates/task-result.md").write_text("synthetic\n", encoding="utf-8")
    (repo / "release" / "allowlist.txt").write_text("# nothing yet\n", encoding="utf-8")
    _git(repo, "init", "-q")
    return repo


def put(repo: Path, relative: str, text: str, *, stage: bool = True) -> None:
    target = repo / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(text.encode("utf-8"))
    if stage:
        _git(repo, "add", "--", relative)


class Outcome:
    def __init__(self, completed: subprocess.CompletedProcess[str]) -> None:
        self.code = completed.returncode
        self.output = completed.stdout + completed.stderr


def run_check(repo: Path, *, extra_path: Path | None = None) -> Outcome:
    """Run the script. ``extra_path`` is put first on PATH *inside* bash (after its startup), so
    that a shim wins even under Git for Windows, whose bash reorders PATH while starting."""
    assert BASH is not None
    env = _env()
    command = ["scripts/check_repo.sh"]
    if extra_path is not None:
        env["QA_SHIM_DIR"] = extra_path.as_posix()
        command = [
            "-c",
            'd=$(cygpath -u "$QA_SHIM_DIR" 2>/dev/null || printf %s "$QA_SHIM_DIR");'
            ' PATH="$d:$PATH"; export PATH; exec "$BASH" "$0"',
            *command,
        ]
    completed = subprocess.run(
        [BASH, *command],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    return Outcome(completed)


# ---- sample secrets, built at runtime ---------------------------------------------------------

GH_SAMPLE = "ghp_" + "Ab1Cd2Ef3Gh4" * 3  # 36 alphanumerics
assert len(GH_SAMPLE) == 4 + 36
SLACK_SAMPLE = "xoxb-" + "1234567890-abcdefghijkl"
AWS_AKIA = "AK" + "IA" + "ABCDEFGH12345678"
AWS_ASIA = "AS" + "IA" + "ABCDEFGH12345678"
assert len(AWS_AKIA) == len(AWS_ASIA) == 20
PGP_HEADER = "-----BEGIN " + "PGP PRIVATE KEY BLOCK" + "-----"
RSA_HEADER = "-----BEGIN " + "RSA PRIVATE KEY" + "-----"
URL_WITH_PW = "postgresql" + "://u:pw@host/db"
API_LINE = "api" + '_key = "abc"'

SHOULD_FLAG = {
    "json_quoted_password": ("config.json", '{"' + PW + '": "x1"}\n', "x1"),
    "yaml_unquoted_password": ("settings.yml", PW + ": " + SAMPLE_CRED + "\n", SAMPLE_CRED),
    "conf_env_style_password": (
        "app.conf",
        "DB_" + PW.upper() + "=" + SAMPLE_CRED + "\n",
        "hunter2",
    ),
    "python_url_with_password": ("client.py", "URL = '" + URL_WITH_PW + "'\n", "u:pw@"),
    "github_token": ("notes.txt", GH_SAMPLE + "\n", GH_SAMPLE),
    "slack_token": ("notes.txt", SLACK_SAMPLE + "\n", SLACK_SAMPLE),
    "aws_akia_key_id": ("notes.txt", AWS_AKIA + "\n", AWS_AKIA),
    "aws_asia_key_id": ("notes.txt", AWS_ASIA + "\n", AWS_ASIA),
    "pgp_private_key_header": ("blob.dat", PGP_HEADER + "\n", PGP_HEADER),
    "rsa_private_key_header": ("blob.dat", RSA_HEADER + "\n", RSA_HEADER),
    "api_key_assignment": ("service.py", API_LINE + "\n", '"abc"'),
}


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return make_repo(tmp_path)


def test_r7_the_baseline_scratch_repo_passes(repo: Path) -> None:
    outcome = run_check(repo)
    assert outcome.code == 0, outcome.output
    assert "check_repo: OK" in outcome.output


@pytest.mark.parametrize("case", SHOULD_FLAG)
def test_r7_secret_shapes_are_flagged(repo: Path, case: str) -> None:
    name, text, needle = SHOULD_FLAG[case]
    put(repo, name, text)
    outcome = run_check(repo)
    assert outcome.code != 0, outcome.output
    assert "POSSIBLE SECRETS" in outcome.output
    assert f"{name}:1" in outcome.output, outcome.output
    assert "check_repo: FAILED" in outcome.output
    assert needle not in outcome.output, "matched content must never be printed"


@pytest.mark.parametrize("case", ["yaml_unquoted_password", "github_token", "api_key_assignment"])
def test_r7_untracked_but_not_ignored_files_are_scanned_too(repo: Path, case: str) -> None:
    name, text, _ = SHOULD_FLAG[case]
    put(repo, name, text, stage=False)
    outcome = run_check(repo)
    assert outcome.code != 0, outcome.output
    assert f"{name}:1" in outcome.output


def test_r7_gitignored_files_are_not_scanned(repo: Path) -> None:
    put(repo, ".gitignore", "local.yml\n")
    put(repo, "local.yml", PW + ": " + SAMPLE_CRED + "\n", stage=False)
    assert run_check(repo).code == 0


PASSES = {
    "dollar_placeholder_quoted_py": ("conf.py", PW + ' = "$' + '{PW}"\n'),
    "dollar_placeholder_json": ("config.json", '{"' + PW + '": "$' + '{PW}"}\n'),
    "dollar_placeholder_yaml": ("settings.yml", PW + ": $" + "{PW}\n"),
    "angle_placeholder_yaml": ("settings.yml", PW + ": <changeme>\n"),
    "angle_placeholder_quoted_json": ("config.json", '{"' + PW + '": "<changeme>"}\n'),
    "angle_placeholder_quoted_py": ("conf.py", PW + ' = "<changeme>"\n'),
    "empty_quoted_py": ("conf.py", PW + ' = ""\n'),
    "empty_quoted_json": ("config.json", '{"' + PW + '": ""}\n'),
    "empty_yaml": ("settings.yml", PW + ":\n"),
    "empty_conf": ("app.conf", "DB_" + PW.upper() + "=\n"),
    "dollar_placeholder_conf": ("app.conf", "DB_" + PW.upper() + "=$" + "{DB_PW}\n"),
    "marker_py": ("conf.py", PW + ' = "' + SAMPLE_CRED + '"  # secret-scan:allow\n'),
    "marker_yaml": ("settings.yml", PW + ": " + SAMPLE_CRED + "  # secret-scan:allow\n"),
    "marker_url": ("client.py", "URL = '" + URL_WITH_PW + "'  # secret-scan:allow\n"),
    "marker_token": ("notes.txt", GH_SAMPLE + "  secret-scan:allow\n"),
    "annotation_not_assignment": ("model.py", "    " + PW + ": str\n"),
    "url_without_password": ("client.py", "URL = 'postgresql" + "://host/db'\n"),
}


@pytest.mark.parametrize("case", PASSES)
def test_r7_placeholders_empty_values_and_marked_lines_pass(repo: Path, case: str) -> None:
    name, text = PASSES[case]
    put(repo, name, text)
    outcome = run_check(repo)
    assert outcome.code == 0, outcome.output
    assert "check_repo: OK" in outcome.output


def test_r7_the_allow_marker_only_covers_its_own_line(repo: Path) -> None:
    text = (
        PW + ' = "' + SAMPLE_CRED + '"  # secret-scan:allow\n'
        "other = 1\n" + PW + ' = "' + SAMPLE_CRED + '"\n'
    )
    put(repo, "conf.py", text)
    outcome = run_check(repo)
    assert outcome.code != 0, outcome.output
    assert "conf.py:3" in outcome.output
    assert "conf.py:1" not in outcome.output


def test_r7_one_clean_and_one_dirty_file_still_fails(repo: Path) -> None:
    put(repo, "clean.py", "x = 1\n")
    put(repo, "dirty.yml", PW + ": " + SAMPLE_CRED + "\n")
    outcome = run_check(repo)
    assert outcome.code != 0
    assert "dirty.yml:1" in outcome.output
    assert "clean.py" not in outcome.output


# ---- fail closed when grep itself errors ------------------------------------------------------


def _shim_grep(directory: Path, *, fail_when_flag: str | None) -> Path:
    """A fake ``grep`` that exits 2. With ``fail_when_flag``, only when that flag is passed;
    otherwise it delegates to the real grep. It records every call in ``calls.log``."""
    directory.mkdir(parents=True, exist_ok=True)
    assert BASH is not None
    real = subprocess.run(
        [BASH, "-c", "command -v grep"], capture_output=True, text=True, check=True, timeout=60
    ).stdout.strip()
    log = (directory / "calls.log").as_posix()
    if fail_when_flag is None:
        body = f'echo "failing call" >> "{log}"\nexit 2\n'
    else:
        body = (
            f'for a in "$@"; do\n'
            f'  if [ "$a" = "{fail_when_flag}" ]; then echo "failing call" >> "{log}"; exit 2; fi\n'
            f"done\n"
            f'echo "delegated call" >> "{log}"\n'
            f'exec "{real}" "$@"\n'
        )
    shim = directory / "grep"
    shim.write_bytes(("#!/bin/sh\n" + body).encode("utf-8"))
    shim.chmod(0o755)
    return directory


def _failing_calls(directory: Path) -> int:
    log = directory / "calls.log"
    if not log.exists():
        return 0
    return log.read_text(encoding="utf-8").count("failing call")


def test_r7_exits_non_zero_when_the_scanning_grep_errors(repo: Path, tmp_path: Path) -> None:
    put(repo, "clean.py", "x = 1\n")
    shim = _shim_grep(tmp_path / "shim-i", fail_when_flag="-InHE")
    outcome = run_check(repo, extra_path=shim)
    if _failing_calls(shim) == 0:
        pytest.skip("the grep shim was never invoked with the scan flags on this host")
    assert outcome.code != 0, outcome.output
    assert "check_repo: FAILED" in outcome.output
    assert "OK" not in outcome.output.replace("FAILED", "")


def test_r7_exits_non_zero_when_every_grep_call_errors(repo: Path, tmp_path: Path) -> None:
    """A grep that always exits 2 must never produce a green check (fail closed throughout)."""
    put(repo, "dirty.yml", PW + ": " + SAMPLE_CRED + "\n")
    shim = _shim_grep(tmp_path / "shim-all", fail_when_flag=None)
    outcome = run_check(repo, extra_path=shim)
    if _failing_calls(shim) == 0:
        pytest.skip("the grep shim was never invoked on this host")
    assert outcome.code != 0, (
        "script reported success although grep itself failed:\n" + outcome.output
    )
    assert "check_repo: OK" not in outcome.output


# Each stage of the script calls grep separately. A grep error (exit 2) in any stage must not turn
# into a green check: plant only what that stage is meant to catch, make just that grep fail, and
# require a non-zero exit. (The generic "every grep fails" test above covers the same ground.)
STAGE_CASES = {
    "forbidden_tracked_files_listing": ("-Ei", lambda r: put(r, ".env.production", "X=1\n")),
    "allowlist_internal_paths": (
        "-Ev",
        lambda r: put(r, "release/allowlist.txt", "docs/" + "adr/decision.md\n"),
    ),
    "scan_file_list_filter": (
        "-zEv",
        lambda r: put(r, "dirty.yml", PW + ": " + SAMPLE_CRED + "\n"),
    ),
    "config_like_file_filter": (
        "-E",
        lambda r: put(r, "dirty.yml", PW + ": " + SAMPLE_CRED + "\n"),
    ),
    "allow_marker_filter": (
        "-v",
        lambda r: put(r, "dirty.py", PW + ' = "' + SAMPLE_CRED + '"\n'),
    ),
}


@pytest.mark.parametrize("stage", STAGE_CASES)
def test_r7_a_grep_error_in_any_single_stage_fails_closed(
    repo: Path, tmp_path: Path, stage: str
) -> None:
    flag, plant = STAGE_CASES[stage]
    plant(repo)
    # Sanity: without the shim the planted problem is detected.
    assert run_check(repo).code != 0, "planted problem is not detected even with a working grep"
    shim = _shim_grep(tmp_path / "shim-stage", fail_when_flag=flag)
    outcome = run_check(repo, extra_path=shim)
    if _failing_calls(shim) == 0:
        pytest.skip(f"grep was never called with {flag} on this host")
    assert outcome.code != 0, (
        f"grep failed (exit 2) in stage '{stage}' but the script exited 0:\n" + outcome.output
    )
