# /commit — Test, Commit, and Push

Run this skill after completing any task to validate, commit, and push changes.

## Steps

### 1. Run the test suite

```bash
.venv/bin/pytest tests/ \
  --ignore=tests/unit/test_scheduler.py \
  --ignore=tests/integration/test_api_activities.py \
  --ignore=tests/integration/test_api_sync.py \
  -q
```

**If tests fail**: stop, report the failures to the user, and do NOT proceed to commit. Fix the failures first.

### 2. Stage changed files

Stage only the files relevant to the current task. Prefer explicit file names over `git add -A`. Do not stage `.env`, secrets, or large binaries.

```bash
git add <relevant files>
```

### 3. Commit with a conventional commit message

```bash
git commit -m "$(cat <<'EOF'
type(scope): short description of what and why

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

Types: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`

### 4. Push

```bash
git push
```

### 5. Report

Tell the user: which files were committed, the commit message used, and that tests passed.
