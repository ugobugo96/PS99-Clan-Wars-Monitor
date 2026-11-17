# PS99 Clan Wars Monitor

A Python 3.9+ Discord bot that stores Roblox-to-Discord registrations in SQLite and checks registered Roblox users during a clan war. It reports confirmed exits from the configured Pet Simulator 99 Roblox experience and reconnections.

## Roblox API reliability and limits

The public `POST https://presence.roblox.com/v1/presence/users` endpoint is officially listed by Roblox as **experimental** and does not require a cookie. Roblox's Creator documentation does not publish a response schema. The endpoint's currently observed response includes a presence type and, for users playing a game, can include `universeId`, `placeId`, and `rootPlaceId` ([community-maintained response reference](https://github.com/NoTwistedHere/Roblox-Apis/blob/main/Documentations/presence.roblox.com.md)). The bot compares the observed `universeId` field with `PS99_UNIVERSE_ID`; this identifies the whole Roblox experience across its places. It does not guess or bundle a Pet Simulator 99 ID. Verify the universe ID with the experience owner or an authoritative Roblox experience page before configuring it.

Because the endpoint and response schema are experimental/undocumented, the response can change and Roblox does not provide a reliability guarantee. Presence reports can also lag, omit game identifiers, or be inaccessible during API/network issues. The bot treats missing/invalid data and request failures as **unknown**, never as a disconnect. It sends an exit alert only after the configured number of consecutive successful responses show the user outside the target universe. Reconnection is reported when a confirmed-away user is observed in the target experience again. The first successful observation in each war is a baseline, so someone already absent when monitoring starts is not falsely reported as having disconnected.

Polling defaults to every 45 seconds (configurable from 30–60 seconds), batches IDs, and honors `Retry-After` on HTTP 429 with bounded retries. Roblox advises clients to handle 429 responses and notes that undocumented limits can apply ([rate limit guidance](https://create.roblox.com/docs/cloud/reference/rate-limits)); it does not publish a stable rate limit for this experimental endpoint. Tune clan size and interval conservatively and review logs for rate limiting. If a batch request fails, all players retain their previous status until the next successful poll.

## Commands

- `/register roblox_username` — link the invoking Discord account to a Roblox username. Roblox resolves the username to a stable numeric user ID. Each Discord account and Roblox account can be registered once.
- `/startwar` — administrator only; resets detection baselines and starts monitoring.
- `/endwar` — administrator only; stops monitoring.
- `/status` — shows registered users and their latest detected status.

Notifications are sent to the configured channel and mention only the affected Discord member. The bot needs permission to view and send messages in that channel. Install it with the `bot` and `applications.commands` scopes; grant View Channels, Send Messages, and Embed Links is not required.

## Setup

1. Create a Discord application and bot in the [Discord Developer Portal](https://discord.com/developers/applications). Invite it to your server with `bot` and `applications.commands` scopes and the permissions above. Keep its token private.
2. Find the verified **universe ID** for the Pet Simulator 99 experience. Do not put a place ID in this setting.
3. Install Python 3.9 or later. In the project directory:

   ```sh
   python3 -m venv .venv
   . .venv/bin/activate
   pip install -r requirements.txt
   cp .env.example .env
   ```

4. Edit `.env`: set `DISCORD_TOKEN`, `NOTIFICATION_CHANNEL_ID`, and `PS99_UNIVERSE_ID`. Never commit `.env`; it is ignored by git.
5. Run locally with `python bot.py`. On startup, the bot creates the SQLite database directory and synchronizes slash commands. Use `/register`, then `/startwar`.

## Configuration

| Variable | Required | Default | Description |
|---|---:|---:|---|
| `DISCORD_TOKEN` | Yes | — | Discord bot token |
| `NOTIFICATION_CHANNEL_ID` | Yes | — | Discord text channel snowflake |
| `PS99_UNIVERSE_ID` | Yes | — | Verified Pet Simulator 99 universe ID |
| `DATABASE_PATH` | No | `data/ps99_bot.sqlite3` | SQLite database path |
| `POLL_INTERVAL_SECONDS` | No | `45` | Poll cadence, 30–60 seconds |
| `DISCONNECT_CONFIRMATION_CHECKS` | No | `2` | Consecutive successful non-PS99 checks before alert |
| `PRESENCE_BATCH_SIZE` | No | `50` | Users per Presence request, 1–100 |
| `LOG_LEVEL` | No | `INFO` | Python logging level |

The active-war flag and registrations are stored in SQLite. After a crash/restart, the bot resumes an active war with fresh detection baselines; the first check establishes current state and avoids emitting alerts for an outage while the bot was down.

## Always-on VM deployment with systemd

Use a small Linux VM. Free VM availability and sleep/retention policies depend on the provider; confirm that its free tier keeps instances running. A conventional always-on VM may require a paid plan if the provider does not offer one free.

1. Copy this project to the VM, install Python 3.9+, create the virtual environment, install requirements, and configure `.env` as above. Restrict `.env` permissions: `chmod 600 .env`.
2. Create a dedicated service account or run the service as your normal deployment user. Adjust paths and username below. Save as `/etc/systemd/system/ps99-clan-wars-monitor.service`:

   ```ini
   [Unit]
   Description=PS99 Clan Wars Monitor Discord bot
   After=network-online.target
   Wants=network-online.target

   [Service]
   Type=simple
   User=YOUR_LINUX_USER
   WorkingDirectory=/opt/ps99-clan-wars-monitor
   EnvironmentFile=/opt/ps99-clan-wars-monitor/.env
   ExecStart=/opt/ps99-clan-wars-monitor/.venv/bin/python /opt/ps99-clan-wars-monitor/bot.py
   Restart=on-failure
   RestartSec=5
   KillSignal=SIGINT
   TimeoutStopSec=30

   [Install]
   WantedBy=multi-user.target
   ```

3. Enable and start it:

   ```sh
   sudo systemctl daemon-reload
   sudo systemctl enable --now ps99-clan-wars-monitor
   sudo systemctl status ps99-clan-wars-monitor
   ```

4. Follow logs with `sudo journalctl -u ps99-clan-wars-monitor -f`. Restart after code/config changes with `sudo systemctl restart ps99-clan-wars-monitor`.

Keep a backup of the SQLite database if registrations matter. Only one bot process should use this database and monitor a given server at a time.

## Checks

Run the included offline unit checks with:

```sh
python3 -m unittest discover -s tests -v
```

They cover presence classification, duplicate registration protection, and disconnect confirmation behavior without requiring Discord credentials or contacting Roblox.
