# Git publication checks

Activate the versioned hooks once in each clone (Python 3 is required):

```bash
git config --local core.hooksPath .githooks
chmod +x .githooks/pre-commit .githooks/commit-msg .githooks/pre-push
```

Before staging a first commit, run:

```bash
python3 scripts/check_repository.py worktree
git status --short
```

The pre-commit hook scans the complete index, including force-added ignored files,
rather than the working copy. The commit-msg hook scans the proposed message.
The pre-push hook scans every locally reachable commit and its files, including
content deleted in later commits and commit messages. This deliberately also
checks other local branches/tags. A scan error blocks the operation.

Checks reject private paths, generated report media, symlinks/submodules, files
over 5 MiB, common credential/token formats, credential-bearing or signed URLs,
and copies of this deployment's `.env`, owner password and embedding token.
Browser-test reports and captures are ignored and blocked even if force-added.
Personal absolute home-directory paths are also blocked; use `<HOME>` in reports.
Diagnostics show filenames and rule names, never matching credential values.
The single exact synthetic database URL in `test_identity.py` is exempt from the
credential-URL rule; local deployment credential checks still apply everywhere.

`.gitignore` keeps local credentials, caches, databases, backups and generated
report media out of ordinary staging. JSON validation reports remain eligible
for versioning and are scanned. `.gitattributes` normalizes text to LF and marks
common binary formats. Existing private files and generated artifacts stay on disk.

These checks are a guardrail, not proof that a repository contains no private
information. Review staged diffs and report contents before publishing. Binary
fixtures cannot be semantically reviewed by this text scanner. Local hooks can
be bypassed or disabled and do not follow a clone automatically; activate them
on each machine. Content already sent to a remote requires credential rotation
and a separate remote/history cleanup, even if later deleted.

Run the guard regression suite with `python3 scripts/test_repository_guard.py`.
Application verification remains `python3 scripts/dev.py verify`; the Git hooks
run the leakage checks and do not rebuild or restart the application.

On 21 October 2026, the initial worktree scan checked 314 eligible files and the
12 guard regression tests passed. No project commits existed at this point.
Seven existing JSON reports had personal home-directory prefixes replaced with
`<HOME>`; measurement values and outcomes were preserved. Generated screenshots
and media remain local and ignored.
The required running-stack verification passed: 199 tests, with one existing
Starlette/httpx deprecation warning.
