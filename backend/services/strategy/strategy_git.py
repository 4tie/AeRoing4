"""services/strategy/strategy_git.py contains backend logic for strategy git.

This file is intentionally documented in plain English so readers can follow
what each section does even without deep Python experience.
"""

from __future__ import annotations
import logging
import subprocess
from datetime import datetime
from pathlib import Path

from ...core.errors import BackendError
from ...models import GitLogEntry

logger = logging.getLogger(__name__)


class StrategyGitService:
    """StrategyGitService contains class-level backend logic."""
    def __init__(self, versions_root: Path) -> None:
        """__init__ implements function-level backend logic."""
        self.versions_root = versions_root

    def git_repo_path(self, strategy_name: str) -> Path:
        """Returns versions_root / strategy_name / "git" """
        return self.versions_root / strategy_name / "git"

    def commit(self, strategy_name: str, source: str, run_id: str) -> str | None:
        """
        Ensure the git repo exists (git init if needed), write source to
        strategy.py, stage it, and commit with message "backtest: {run_id}".
        Returns the 40-char SHA on success, None on any failure (logs a warning).
        """
        repo = self.git_repo_path(strategy_name)

        try:
            # Initialise repo if it doesn't exist yet
            if not (repo / ".git").exists():
                repo.mkdir(parents=True, exist_ok=True)
                result = subprocess.run(
                    ["git", "init"],
                    cwd=repo,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if result.returncode != 0:
                    logger.warning(
                        "git init failed for %s: %s",
                        strategy_name,
                        result.stderr.strip(),
                    )
                    return None

                # Set git identity so commits don't fail in environments without
                # a global git config
                for cmd in (
                    ["git", "config", "user.email", "strategy-lab@local"],
                    ["git", "config", "user.name", "Strategy Lab"],
                ):
                    cfg = subprocess.run(
                        cmd,
                        cwd=repo,
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    if cfg.returncode != 0:
                        logger.warning(
                            "git config failed for %s: %s",
                            strategy_name,
                            cfg.stderr.strip(),
                        )
                        return None

            # Write the strategy source
            strategy_file = repo / "strategy.py"
            strategy_file.write_text(source, encoding="utf-8")

            # Stage the file
            add_result = subprocess.run(
                ["git", "add", "strategy.py"],
                cwd=repo,
                capture_output=True,
                text=True,
                check=False,
            )
            if add_result.returncode != 0:
                logger.warning(
                    "git add failed for %s: %s",
                    strategy_name,
                    add_result.stderr.strip(),
                )
                return None

            # If nothing changed, return the existing HEAD SHA
            diff_result = subprocess.run(
                ["git", "diff", "--cached", "--quiet"],
                cwd=repo,
                capture_output=True,
                check=False,
            )
            if diff_result.returncode == 0:
                rev_result = subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    cwd=repo,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                sha = rev_result.stdout.strip()
                return sha if len(sha) == 40 else None

            # Commit
            message = f"backtest: {run_id}"
            commit_result = subprocess.run(
                ["git", "commit", "-m", message],
                cwd=repo,
                capture_output=True,
                text=True,
                check=False,
            )
            if commit_result.returncode != 0:
                logger.warning(
                    "git commit failed for %s: %s",
                    strategy_name,
                    commit_result.stderr.strip(),
                )
                return None

            # Retrieve the 40-char SHA of the new commit
            rev_result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo,
                capture_output=True,
                text=True,
                check=False,
            )
            if rev_result.returncode != 0:
                logger.warning(
                    "git rev-parse failed for %s: %s",
                    strategy_name,
                    rev_result.stderr.strip(),
                )
                return None

            sha = rev_result.stdout.strip()
            if len(sha) != 40:
                logger.warning(
                    "Unexpected SHA length for %s: %r",
                    strategy_name,
                    sha,
                )
                return None

            return sha

        except FileNotFoundError:
            logger.warning(
                "git executable not found; skipping commit for %s",
                strategy_name,
            )
            return None

    def log(self, strategy_name: str) -> list[GitLogEntry]:
        """
        Returns commits in reverse-chronological order.
        Raises BackendError(404) if the repo does not exist.
        """
        repo_path = self.git_repo_path(strategy_name)
        if not repo_path.exists():
            raise BackendError(
                f"Git repository for strategy '{strategy_name}' does not exist.",
                status_code=404,
            )

        result = subprocess.run(
            ["git", "log", "--format=%H|%s|%aI"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=False,
        )

        entries: list[GitLogEntry] = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split("|", 2)
            if len(parts) != 3:
                continue
            sha, message, timestamp_str = parts
            try:
                timestamp = datetime.fromisoformat(timestamp_str)
            except ValueError:
                logger.warning("Could not parse git log timestamp: %r", timestamp_str)
                continue

            # Extract run_id from message if it follows the "backtest: {run_id}" convention
            run_id: str | None = None
            if message.startswith("backtest: "):
                parts_msg = message.split(": ", 1)
                if len(parts_msg) == 2:
                    run_id = parts_msg[1]

            entries.append(
                GitLogEntry(
                    sha=sha,
                    message=message,
                    timestamp=timestamp,
                    run_id=run_id,
                )
            )

        return entries

    def diff(self, strategy_name: str, sha_a: str, sha_b: str) -> str:
        """
        Returns the unified diff of strategy.py between sha_a and sha_b.
        Raises BackendError(404) if the repo does not exist or either SHA is unknown
        (detected via non-zero exit code from git diff).
        """
        repo_path = self.git_repo_path(strategy_name)
        if not repo_path.exists():
            raise BackendError(
                f"Git repository for strategy '{strategy_name}' does not exist.",
                status_code=404,
            )

        result = subprocess.run(
            ["git", "diff", sha_a, sha_b, "--", "strategy.py"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=False,
        )

        if result.returncode != 0:
            raise BackendError(
                f"Unknown SHA in diff request for strategy '{strategy_name}': "
                f"sha_a={sha_a!r}, sha_b={sha_b!r}. {result.stderr.strip()}",
                status_code=404,
            )

        return result.stdout

    def show(self, strategy_name: str, sha: str) -> str:
        """
        Returns the full content of strategy.py at the given commit SHA.
        Raises BackendError(404) if the repo does not exist or the SHA is unknown.
        """
        repo_path = self.git_repo_path(strategy_name)
        if not repo_path.exists():
            raise BackendError(
                f"Git repository for strategy '{strategy_name}' does not exist.",
                status_code=404,
            )
        result = subprocess.run(
            ["git", "show", f"{sha}:strategy.py"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise BackendError(
                f"Unknown SHA '{sha}' for strategy '{strategy_name}'.",
                status_code=404,
            )
        return result.stdout

    def restore(self, strategy_name: str, sha: str) -> str:
        """
        Restores strategy.py to the given commit SHA by checking out that file.
        Returns the restored content.
        Raises BackendError(404) if the repo does not exist or the SHA is unknown.
        """
        repo_path = self.git_repo_path(strategy_name)
        if not repo_path.exists():
            raise BackendError(
                f"Git repository for strategy '{strategy_name}' does not exist.",
                status_code=404,
            )
        result = subprocess.run(
            ["git", "checkout", f"{sha}", "--", "strategy.py"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise BackendError(
                f"Failed to restore SHA '{sha}' for strategy '{strategy_name}': {result.stderr.strip()}",
                status_code=404,
            )
        # Read the restored content
        strategy_file = repo_path / "strategy.py"
        return strategy_file.read_text(encoding="utf-8")
