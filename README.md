# LeetCode Telegram Reporter Bot

A simple but powerful Telegram bot that tracks LeetCode submissions for a list of users and posts daily reports in a group chat.

## 🌟 Features

* **Track Multiple Users:** Add any number of LeetCode users to the tracking list.
* **Human-Readable Names:** Track `johndoe123` but display their name as "John Doe" in reports.
* **Fetches Problem Difficulty:** Reports include whether a problem was 🟢 Easy, 🟠 Medium, or 🔴 Hard.
* **Automated Daily Reports:** Automatically posts a summary of the *previous day's* (UTC) solved problems at a set time (15:00 UTC).
* **Manual Reports:**
    * `/send_report`: Manually trigger a report for *yesterday*.
    * `/send_today`: Manually trigger a report for *today* (so far).
* **Reliable & Efficient:**
    * Uses a local SQLite database to cache problem data and avoid duplicate posts.
    * Designed to run 24/7 as a `systemd` service on a Linux server.

-----

## 🚀 Deployment Guide (DigitalOcean + Ubuntu)

This guide walks through deploying the bot to a DigitalOcean Droplet (or any Ubuntu 22.04 VPS).

### 1\. Prerequisites (Local Machine)

Before deploying, make sure your project is ready.

1.  **Use Environment Variables:** Ensure your `bot.py` reads the token from the environment.

    * `import os`
    * `TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")`

2.  **Create `requirements.txt`:** If you don't have one, create it from your local venv.

    ```bash
    # Activate your local venv
    pip freeze > requirements.txt
    ```

3.  **Push to Git:** Push your complete code (`bot.py`, `leetcode_api.py`, `requirements.txt`) to a GitHub or GitLab repository.

### 2\. Initial Server Setup

1.  **Create a Droplet:**

    * **Provider:** DigitalOcean (or any VPS).
    * **Image:** **Ubuntu 22.04 (LTS)**.
    * **Plan:** The cheapest "Basic" Droplet (1GB RAM) is sufficient.
    * **Authentication:** **SSH Keys**. Add your local public SSH key. **Do not use a password.**

2.  **Log in as `root`:**

    ```bash
    ssh root@YOUR_SERVER_IP
    ```

3.  **Create a Secure User:**

    * Create a new user (e.g., `botadmin`).
      ```bash
      adduser botadmin
      ```
    * Give it `sudo` (admin) privileges:
      ```bash
      usermod -aG sudo botadmin
      ```
    * Copy your SSH key to the new user so you can log in directly:
      ```bash
      mkdir -p /home/botadmin/.ssh
      cp /root/.ssh/authorized_keys /home/botadmin/.ssh/authorized_keys
      chown -R botadmin:botadmin /home/botadmin/.ssh
      chmod 700 /home/botadmin/.ssh
      chmod 600 /home/botadmin/.ssh/authorized_keys
      ```
    * Log out of the `root` session:
      ```bash
      exit
      ```

### 3\. Prepare the Bot Environment

1.  **Log in as Your New User:**

    ```bash
    ssh botadmin@YOUR_SERVER_IP
    ```

2.  **Update System & Install Tools:**

    ```bash
    sudo apt update
    sudo apt upgrade -y
    sudo apt install python3-pip python3-venv git -y
    ```

3.  **Clone Your Project:**

    * Create a directory for the bot.
      ```bash
      mkdir ~/leetcode-bot
      cd ~/leetcode-bot
      ```
    * Clone your repo (use the HTTPS URL).
      ```bash
      # Replace this with your own repo URL
      git clone https://github.com/chorobaev/telegram-leetcode-reporter-bot.git .
      ```

4.  **Set Up Python venv:**

    ```bash
    # Create the virtual environment
    python3 -m venv venv

    # Activate it
    source venv/bin/activate

    # Install all required libraries
    pip install -r requirements.txt

    # You can deactivate for now
    deactivate
    ```

### 4\. Run 24/7 with `systemd`

We will create a service to auto-start your bot and restart it if it crashes.

1.  **Create the Service File:**

    ```bash
    sudo nano /etc/systemd/system/leetcode-bot.service
    ```

2.  **Paste This Configuration:**

    * Copy and paste the template below.
    * **Crucially, edit the 4 highlighted items:**
        1.  `User` (e.g., `botadmin`)
        2.  `WorkingDirectory` (the full path to your code)
        3.  `ExecStart` (the full path to your venv's `python3`)
        4.  The `Environment` variable (paste your real Telegram token here).

    <!-- end list -->

    ```ini
    [Unit]
    Description=LeetCode Telegram Bot
    After=network.target

    [Service]
    User=botadmin
    Group=botadmin
    WorkingDirectory=/home/botadmin/leetcode-bot
    ExecStart=/home/botadmin/leetcode-bot/venv/bin/python3 bot.py

    # --- !! IMPORTANT !! ---
    # Put your bot token here. The bot reads this as an environment variable.
    Environment="TELEGRAM_BOT_TOKEN=123456:ABC-DEFG..."

    # --- Keep the bot running ---
    Restart=on-failure
    RestartSec=5s

    [Install]
    WantedBy=multi-user.target
    ```

3.  **Save and Exit `nano`:**

    * Press `Ctrl+X`.
    * Press `Y` (to save).
    * Press `Enter` (to confirm the file name).

4.  **Start Your Bot Service:**

    ```bash
    # 1. Reload systemd to find your new file
    sudo systemctl daemon-reload

    # 2. Enable the service (so it auto-starts on server boot)
    sudo systemctl enable leetcode-bot

    # 3. Start the service right now
    sudo systemctl start leetcode-bot
    ```

### 5\. Check Your Bot

Your bot is now running\!

* **Check Status:**

  ```bash
  sudo systemctl status leetcode-bot
  ```

  (Look for `active (running)` in green. Press `q` to quit.)

* **View Live Logs (Most Important\!):**

  ```bash
  sudo journalctl -u leetcode-bot -f
  ```

  (This shows all your `print()` and `logging` messages in real-time. This is how you debug.)

* **To Restart Your Bot (e.g., after an update):**

  ```bash
  sudo systemctl restart leetcode-bot
  ```

### 6\. Updating Your Bot

To deploy new code changes:

1.  Log in: `ssh botadmin@YOUR_SERVER_IP`
2.  Go to the folder: `cd ~/leetcode-bot`
3.  Pull new code: `git pull`
4.  Restart the service: `sudo systemctl restart leetcode-bot`

-----

## 🤖 Bot Usage (Commands)

* `/start` - Shows the welcome message.
* `/help` - Lists all available commands.

### Admin Commands

* `/register_group` - (Must be run *inside* the group) Registers that group as the destination for all reports.
* `/add <leetcode_username> <display_name>` - Starts tracking a user.
    * *Example:* `/add neal_wu Neal Wu`
* `/remove <leetcode_username>` - Stops tracking a user.
* `/list` - Shows all users currently being tracked.
* `/send_report` - Manually posts the report for *yesterday's* (UTC) activity.
* `/send_today` - Manually posts the report for *today's* (UTC) activity so far.

-----

## 📁 Project Structure

```
/
├── bot.py             # Main bot logic, commands, and scheduler
├── leetcode_api.py    # Functions to query LeetCode's GraphQL API
├── requirements.txt   # Python dependencies
├── leetcode_bot.db    # SQLite database (auto-created on first run)
└── README.md          # This file
```
