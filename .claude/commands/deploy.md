# /deploy — Commit and Deploy to VPS

Run this skill to commit, push, and deploy to the Hetzner VPS. This wraps `/commit` — do not duplicate its logic.

## Steps

### 1. Commit and push

Run the `/commit` skill first. If it fails (tests failing or nothing to commit), stop here and report to the user.

### 2. Load VPS IP from environment

```bash
source .env
```

`VPS_IP` is now available for the commands below.

### 3. Pull code on VPS

```bash
ssh fitness@$VPS_IP "cd /home/fitness/fitness && git pull"
```

### 4. Install any new dependencies (if `pyproject.toml` changed)

```bash
ssh fitness@$VPS_IP "cd /home/fitness/fitness && .venv/bin/pip install -e . -q"
```

Run this step only if `pyproject.toml` was part of the commit. Skip it otherwise.

### 5. Restart the service

```bash
ssh fitness@$VPS_IP "sudo /usr/bin/systemctl restart fitness-bot"
```

Note: the `fitness` user has passwordless sudo for this exact command. Do not add flags — extra flags break the sudoers match.

### 6. Verify clean startup

```bash
ssh fitness@$VPS_IP "sudo /usr/bin/systemctl status fitness-bot"
```

Check the output for errors. If the service failed to start, report the status output to the user and do not mark the deploy as successful.

For detailed logs if needed:

```bash
ssh fitness@$VPS_IP "journalctl -u fitness-bot --no-pager -n 30"
```

### 6. Report

Tell the user: the commit that was deployed, whether pip deps were reinstalled, and the service status confirming clean startup.
