# Test Bot Deployment (Side-by-side)

This guide sets up a test instance alongside production using systemd, a separate checkout, a separate virtualenv, a separate Telegram token, and a separate SQLite DB.

## 1) Create a Separate Checkout

Example path (adjust to your server/user):

```
mkdir -p /opt/dsa-watchman-test
cd /opt/dsa-watchman-test
git clone https://github.com/chorobaev/telegram-leetcode-reporter-bot.git .
```

## 2) Create a Dedicated Virtualenv

```
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
deactivate
```

## 3) Create a Test Environment File

Create `/opt/dsa-watchman-test/.env`:

```
TELEGRAM_BOT_TOKEN=123456:TEST-TOKEN
DB_NAME=/opt/dsa-watchman-test/leetcode_bot_test.db
```

## 4) Create a Systemd Service for Test

Create `/etc/systemd/system/dsa-watchman-test.service`:

```
[Unit]
Description=LeetCode Telegram Bot (Test)
After=network.target

[Service]
User=botadmin
Group=botadmin
WorkingDirectory=/opt/dsa-watchman-test
ExecStart=/opt/dsa-watchman-test/venv/bin/python3 bot.py

EnvironmentFile=/opt/dsa-watchman-test/.env

Restart=on-failure
RestartSec=5s

[Install]
WantedBy=multi-user.target
```

## 5) Enable and Start

```
sudo systemctl daemon-reload
sudo systemctl enable dsa-watchman-test
sudo systemctl start dsa-watchman-test
```

## 6) Verify

```
sudo systemctl status dsa-watchman-test
sudo journalctl -u dsa-watchman-test -f
```

## 7) Register Test Groups

Use the test bot token to add the bot to your test group(s), then run:

```
/register_group
```

## Notes

- Production service stays unchanged.
- Test DB is isolated via `DB_NAME` in the env file.
- If you update code in the test checkout, restart only the test service.
