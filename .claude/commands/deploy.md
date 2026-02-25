# /deploy — Commit and Deploy to VPS

Run this skill to commit, push, and deploy to the Hetzner VPS. This wraps `/commit` — do not duplicate its logic.

## Steps

### 1. Commit and push

Run the `/commit` skill first. If it fails (tests failing or nothing to commit), stop here and report to the user.

### 2. Read VPS IP from environment

```bash
source .env
```

The `VPS_IP` variable is now available.

### 3. Pull code on VPS (as the `fitness` user)

```bash
ssh root@$VPS_IP "su - fitness -c 'cd /home/fitness/fitness && git pull'"
```

### 4. Install any new dependencies (if `pyproject.toml` changed)

```bash
ssh root@$VPS_IP "su - fitness -c 'cd /home/fitness/fitness && .venv/bin/pip install -e . -q'"
```

Run this step if `pyproject.toml` was part of the commit. Skip it otherwise.

### 5. Restart the service

```bash
ssh root@$VPS_IP "systemctl restart fitness-bot"
```

### 6. Verify clean startup

```bash
ssh root@$VPS_IP "journalctl -u fitness-bot --no-pager -n 30"
```

Check the output for errors. If the service failed to start, report the log tail to the user and do not mark the deploy as successful.

### 7. Report

Tell the user: the commit that was deployed, whether pip deps were reinstalled, and the last few log lines confirming clean startup.
