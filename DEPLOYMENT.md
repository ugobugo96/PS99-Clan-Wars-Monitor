# Cloud Deployment Guide

This guide runs PS99 Clan Wars Monitor as a single Python service on an Ubuntu Linux VM. It does not deploy the bot or create a cloud account for you.

## What the service needs

- Python 3.9 or newer.
- Outbound HTTPS access to Discord and Roblox. The bot does not need an inbound web port.
- A persistent writable directory for the SQLite database.
- One running bot process for a given database and Discord server.

The entry point is `bot.py`. Dependencies are listed in `requirements.txt` and installed with pip. SQLite is included with Python; no separate database server is required.

## Configure environment variables

Set the following variables in your hosting provider's environment-variable settings, or in a protected `.env` file on a VM. Never commit the real `.env` file.

| Variable | Required | Default | Notes |
|---|---:|---|---|
| `DISCORD_TOKEN` | Yes | — | Discord bot token. Store as a secret in the provider. |
| `NOTIFICATION_CHANNEL_ID` | Yes | — | Discord channel ID containing digits only. |
| `PS99_UNIVERSE_ID` | Yes | — | Verified Roblox experience universe ID, not a place ID. |
| `DATABASE_PATH` | No | `data/ps99_bot.sqlite3` | Set to an absolute path on persistent storage for cloud hosting. |
| `POLL_INTERVAL_SECONDS` | No | `45` | Must be between 30 and 60 seconds. |
| `DISCONNECT_CONFIRMATION_CHECKS` | No | `2` | Consecutive successful checks required before an exit alert. |
| `PRESENCE_BATCH_SIZE` | No | `50` | Users per Roblox request; allowed range is 1–100. |
| `LOG_LEVEL` | No | `INFO` | Standard Python level such as `INFO` or `DEBUG`. |

The repository includes `.env.example` with placeholders. Copy it to `.env` only for local use, replace every required placeholder, and protect it with `chmod 600 .env`. Do not put quotes around values unless the value itself requires them. Hosting dashboards usually set these variables directly, so a `.env` file is not required on those platforms.

## Install and run

On a server or local machine with Python 3.9+:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python bot.py
```

The bot validates required settings at startup. It creates the parent directory for `DATABASE_PATH` if it does not exist. A normal Linux shutdown or systemd stop lets discord.py close its HTTP session and SQLite connection. discord.py reconnects the Discord Gateway automatically after transient connection loss; systemd can restart the whole process after a crash.

## Persistent SQLite storage

Many app-hosting filesystems are temporary and can be erased on restart or redeploy. If using a platform with mounted disks or volumes:

1. Attach a persistent disk/volume to the service.
2. Set `DATABASE_PATH` to a file inside that mounted directory, for example `/var/lib/ps99-clan-wars-monitor/ps99_bot.sqlite3`.
3. Ensure the service account can write to the directory.
4. Keep one bot instance attached to that database. The bot also takes an OS-level lock next to the database and exits with an error if another process on that server tries to use it simultaneously.

If you use the default relative `data/ps99_bot.sqlite3`, it is stored under the service's working directory. That is persistent on a conventional VM disk, but may not be persistent on a container or managed app platform. Back up the SQLite database before replacing a VM or changing storage. Do not copy or delete the database while the bot is running.

The process lock protects against multiple local processes sharing the same database path. Do not run multiple servers/replicas against one SQLite database; SQLite and this lock are not a distributed coordination system.

## Ubuntu VM with systemd

The commands below assume the project is at `/opt/ps99-clan-wars-monitor` and the Linux service user is `ps99bot`. Substitute your actual username and project path consistently.

### 1. Install system packages

```sh
sudo apt update
sudo apt install -y python3 python3-venv python3-pip ca-certificates
```

### 2. Copy the project and install Python dependencies

Copy the project to `/opt/ps99-clan-wars-monitor` using your chosen secure file-transfer or Git method. Create a dedicated user if you do not already have one:

```sh
sudo adduser --system --group --home /opt/ps99-clan-wars-monitor ps99bot
sudo chown -R ps99bot:ps99bot /opt/ps99-clan-wars-monitor
sudo -u ps99bot python3 -m venv /opt/ps99-clan-wars-monitor/.venv
sudo -u ps99bot /opt/ps99-clan-wars-monitor/.venv/bin/python -m pip install --upgrade pip
sudo -u ps99bot /opt/ps99-clan-wars-monitor/.venv/bin/pip install -r /opt/ps99-clan-wars-monitor/requirements.txt
```

If you already have a Linux service user, use it instead of creating another account.

### 3. Create a persistent data directory and environment file

```sh
sudo install -d -o ps99bot -g ps99bot -m 750 /var/lib/ps99-clan-wars-monitor
sudo install -o ps99bot -g ps99bot -m 600 /dev/null /etc/ps99-clan-wars-monitor.env
sudoedit /etc/ps99-clan-wars-monitor.env
```

Add the required variables and any optional values to that file. Example structure (replace every placeholder locally; never paste a real token into chat or commit it):

```dotenv
DISCORD_TOKEN=your_discord_bot_token
NOTIFICATION_CHANNEL_ID=123456789012345678
PS99_UNIVERSE_ID=3317771874
DATABASE_PATH=/var/lib/ps99-clan-wars-monitor/ps99_bot.sqlite3
POLL_INTERVAL_SECONDS=45
DISCONNECT_CONFIRMATION_CHECKS=2
PRESENCE_BATCH_SIZE=50
LOG_LEVEL=INFO
```

The example universe ID is shown only as an example; verify the intended experience ID before using it. Ensure the file remains restricted:

```sh
sudo chown root:ps99bot /etc/ps99-clan-wars-monitor.env
sudo chmod 640 /etc/ps99-clan-wars-monitor.env
```

### 4. Create the systemd service

Create `/etc/systemd/system/ps99-clan-wars-monitor.service`:

```ini
[Unit]
Description=PS99 Clan Wars Monitor Discord bot
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User=ps99bot
Group=ps99bot
WorkingDirectory=/opt/ps99-clan-wars-monitor
EnvironmentFile=/etc/ps99-clan-wars-monitor.env
ExecStart=/opt/ps99-clan-wars-monitor/.venv/bin/python /opt/ps99-clan-wars-monitor/bot.py
Restart=on-failure
RestartSec=5
KillSignal=SIGINT
TimeoutStopSec=30
UMask=0077

[Install]
WantedBy=multi-user.target
```

Then enable it at boot and start it now:

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now ps99-clan-wars-monitor
sudo systemctl status ps99-clan-wars-monitor
```

`Restart=on-failure` restarts the bot after an unexpected non-zero exit. `enable` starts it automatically after a server reboot. The single-instance lock prevents a second process using the same database on that server.

### 5. View logs and operate the service

```sh
sudo journalctl -u ps99-clan-wars-monitor -f
sudo systemctl restart ps99-clan-wars-monitor
sudo systemctl stop ps99-clan-wars-monitor
```

Standard output and Python logs are collected by journald and can be viewed in the server console. Do not run `python bot.py` manually while the systemd service is active; the lock will reject the second copy.

## Deploying updates

Before changing code or replacing a server, back up the SQLite file while the bot is stopped. Install the updated project and requirements, then restart the systemd service. Do not run two bot instances during a migration. The bot stores registration and war state in SQLite and resumes a saved active war after restart with fresh presence baselines.

## Offline checks

Run tests from the project root:

```sh
python -m unittest discover -s tests -v
```

These checks use temporary or in-memory SQLite databases and do not require Discord credentials or contact Roblox.
