import sqlite3
import logging
import datetime
import os
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.constants import ParseMode

# Import our LeetCode API function from the other file
try:
    from leetcode_api import fetch_recent_submissions, fetch_problem_difficulty
except ImportError:
    print("!!! ERROR: Make sure 'leetcode_api.py' is in the same directory.")
    exit(1)

# --- Configuration ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
DB_NAME = os.environ.get("DB_NAME", "leetcode_bot.db")
CHECK_INTERVAL_SECONDS = 3600  # 3600 seconds = 1 hour

if not TELEGRAM_BOT_TOKEN:
    print("!!! ERROR: TELEGRAM_BOT_TOKEN environment variable not set.")
    exit(1)

# --- Database Setup ---
def init_db():
    """Initializes the SQLite database and creates tables if they don't exist."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # Table to store the group chat ID where updates should be posted
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS groups (
        chat_id INTEGER PRIMARY KEY NOT NULL
    )
    """)

    # Table to store tracked users per group
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS group_tracked_users (
        chat_id INTEGER NOT NULL,
        leetcode_username TEXT NOT NULL,
        display_name TEXT NOT NULL,
        PRIMARY KEY (chat_id, leetcode_username)
    )
    """)

    # Table to log problems that have been posted for the day
    # This prevents duplicate posts if the script runs multiple times.
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS posted_today (
        chat_id INTEGER NOT NULL,
        leetcode_username TEXT NOT NULL,
        problem_slug TEXT NOT NULL,
        date_posted TEXT NOT NULL,
        PRIMARY KEY (chat_id, leetcode_username, problem_slug, date_posted)
    )
    """)

    # Table to cache problem difficulties. This avoids
    # hitting the LeetCode API for the same problem multiple times.
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS problem_info (
        problem_slug TEXT PRIMARY KEY NOT NULL,
        difficulty TEXT NOT NULL,
        title TEXT NOT NULL
    )
    """)

    # Table to store per-user streak info for reports
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS user_streaks (
        leetcode_username TEXT PRIMARY KEY NOT NULL,
        last_date TEXT NOT NULL,
        streak_value INTEGER NOT NULL
    )
    """)

    conn.commit()
    conn.close()
    print("Database initialized successfully.")

# --- Bot Command Handlers ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /start command."""
    await update.message.reply_text(
        "👋 Welcome to the LeET-Tracker Bot!\n\n"
        "I post updates in your group when tracked users solve LeetCode problems.\n\n"
        "Here's how to get started:\n"
        "1. Add me to your Telegram group.\n"
        "2. Make me an admin (so I can post messages).\n"
        "3. Type `/register_group` in that group.\n"
        "4. Use `/add <leetcode_username>` to start tracking."
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /help command."""
    await update.message.reply_text(
        "Here are the available commands:\n\n"
        "👤 **User Management:**\n"
        "  `/add <username> <display_name>` - Start tracking a LeetCode user.\n"
        "  `/remove <username>` - Stop tracking a LeetCode user.\n"
        "  `/list` - Show all LeET-Tracker users being tracked.\n\n"
        "⚙️ **Group Setup:**\n"
        "  `/register_group` - (Run in your group) Sets this group as the one for posting updates.\n"
        "  `/send_report` - Manually post YESTERDAY's report.\n"
        "  `/send_today` - Manually post TODAY's report (so far).\n\n"
        "🛠️ **Admin Tools:**\n"
        "  `/set_streak <username> <streak_number>` - (Admins only) Set a tracked user's streak."
    )


async def user_is_group_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Returns True if command sender is a group admin or owner."""
    chat_member = await context.bot.get_chat_member(
        chat_id=update.message.chat_id,
        user_id=update.message.from_user.id
    )
    return chat_member.status in ("administrator", "creator")


async def register_group_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /register_group command. Stores the chat_id."""
    chat_id = update.message.chat_id

    if update.message.chat.type == "private":
        await update.message.reply_text("Please run this command inside the Telegram group where you want me to post updates, not in a private chat.")
        return

    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO groups (chat_id) VALUES (?)", (chat_id,))
        conn.commit()
        conn.close()

        await update.message.reply_text(
            f"✅ Success! This group (Chat ID: {chat_id}) is now registered for LeetCode updates."
        )
        logging.info(f"Group registered: {chat_id}")

    except Exception as e:
        await update.message.reply_text(f"An error occurred while registering the group: {e}")
        logging.error(f"Error registering group: {e}")

async def add_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /add <username> command."""
    if update.message.chat.type == "private":
        await update.message.reply_text("Please use `/add` inside your group, not in a private chat.")
        return

    if len(context.args) < 2:
        await update.message.reply_text(
            "Usage: `/add <leetcode_username> <display_name>`\n"
            "Example: `/add neal_wu Neal Wu`"
        )
        return

    username_to_add = context.args[0].strip()
    # Join all remaining arguments to form the display name
    display_name = " ".join(context.args[1:])

    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM groups WHERE chat_id = ?", (update.message.chat_id,))
        if not cursor.fetchone():
            await update.message.reply_text("This group is not registered yet. Run `/register_group` first.")
            conn.close()
            return

        cursor.execute(
            "INSERT OR IGNORE INTO group_tracked_users (chat_id, leetcode_username, display_name) VALUES (?, ?, ?)",
            (update.message.chat_id, username_to_add, display_name)
        )
        conn.commit()

        if cursor.rowcount > 0:
            await update.message.reply_text(f"✅ User '{username_to_add}' is now being tracked as '{display_name}'.")
            logging.info(f"Added user: {username_to_add} as {display_name}")
        else:
            await update.message.reply_text(f"User '{username_to_add}' is already being tracked.")

        conn.close()

    except Exception as e:
        await update.message.reply_text(f"An error occurred while adding the user: {e}")
        logging.error(f"Error adding user: {e}")

async def remove_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /remove <username> command."""
    if update.message.chat.type == "private":
        await update.message.reply_text("Please use `/remove` inside your group, not in a private chat.")
        return

    if not context.args:
        await update.message.reply_text("Usage: `/remove <leetcode_username>`\nExample: `/remove neal_wu`")
        return

    username_to_remove = context.args[0].strip()

    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM group_tracked_users WHERE chat_id = ? AND leetcode_username = ?",
            (update.message.chat_id, username_to_remove)
        )
        conn.commit()

        if cursor.rowcount > 0:
            await update.message.reply_text(f"❌ User '{username_to_remove}' has been removed.")
            logging.info(f"Removed user: {username_to_remove}")
        else:
            await update.message.reply_text(f"User '{username_to_remove}' was not found in the tracking list.")

        conn.close()

    except Exception as e:
        await update.message.reply_text(f"An error occurred while removing the user: {e}")
        logging.error(f"Error removing user: {e}")

async def list_users_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /list command."""
    if update.message.chat.type == "private":
        await update.message.reply_text("Please use `/list` inside your group, not in a private chat.")
        return

    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT leetcode_username, display_name FROM group_tracked_users WHERE chat_id = ? ORDER BY display_name",
            (update.message.chat_id,)
        )
        users = cursor.fetchall()
        conn.close()

        if not users:
            await update.message.reply_text("No LeetCode users are currently being tracked. Use `/add <username>` to add one.")
            return

        message = "📈 Currently Tracked LeetCode Users:\n"
        for i, user in enumerate(users):
            # user[0] is leetcode_username, user[1] is display_name
            message += f"  {i+1}. {user[1]} ({user[0]})\n"

        await update.message.reply_text(message)

    except Exception as e:
        await update.message.reply_text(f"An error occurred while listing users: {e}")
        logging.error(f"Error listing users: {e}")

async def manual_send_report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Starts manually sending the previous day's report.
    """
    if update.message.chat.type == "private":
        await update.message.reply_text("Please use `/send_report` inside your group, not in a private chat.")
        return

    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM groups WHERE chat_id = ?", (update.message.chat_id,))
        if not cursor.fetchone():
            await update.message.reply_text("This group is not registered yet. Run `/register_group` first.")
            conn.close()
            return
        conn.close()
    except Exception as e:
        await update.message.reply_text(f"Failed to verify group registration: {e}")
        return

    logging.info(f"Manual YESTERDAY report triggered by {update.message.from_user.username}")
    await update.message.reply_text("Кечээки (UTC) отчет даярдалууда...")

    # Calculate yesterday's date
    yesterday_utc = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)
    yesterday_utc_str = yesterday_utc.strftime('%Y-%m-%d')

    try:
        # Call the main function with "Yesterday"
        sent = await generate_and_send_report(
            context,
            update.message.chat_id,
            yesterday_utc_str,
            "Кечээки",
            update_streaks=False
        )
        if not sent:
            await update.message.reply_text("Кечээки күн үчүн чечилген маселелер табылган жок.")
    except Exception as e:
        logging.error(f"Manual report trigger failed: {e}")
        await update.message.reply_text(f"Отчет даярдоодо ката кетти: {e}")

async def manual_send_today_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Starts manually sending today's report.
    """
    if update.message.chat.type == "private":
        await update.message.reply_text("Please use `/send_today` inside your group, not in a private chat.")
        return

    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM groups WHERE chat_id = ?", (update.message.chat_id,))
        if not cursor.fetchone():
            await update.message.reply_text("This group is not registered yet. Run `/register_group` first.")
            conn.close()
            return
        conn.close()
    except Exception as e:
        await update.message.reply_text(f"Failed to verify group registration: {e}")
        return

    logging.info(f"Manual TODAY report triggered by {update.message.from_user.username}")
    await update.message.reply_text(
        "Бүгүнкү (UTC) отчет даярдалууда...\n"
        "Маалымат 1 саатка чейин кечигиши мүмкүн, анткени маалыматтар мезгил-мезгили менен чогултулат."
    )

    # Calculate today's date
    today_utc = datetime.datetime.now(datetime.timezone.utc)
    today_utc_str = today_utc.strftime('%Y-%m-%d')

    try:
        # Call the main function with "Today"
        sent = await generate_and_send_report(
            context,
            update.message.chat_id,
            today_utc_str,
            "Бүгүнкү",
            update_streaks=False
        )
        if not sent:
            await update.message.reply_text("Бүгүнкү күн үчүн чечилген маселелер азырынча табылган жок.")
    except Exception as e:
        logging.error(f"Manual today report trigger failed: {e}")
        await update.message.reply_text(f"Отчет даярдоодо ката кетти: {e}")


async def set_streak_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /set_streak <username> <streak_number> command."""
    if update.message.chat.type == "private":
        await update.message.reply_text("Please use `/set_streak` inside your group, not in a private chat.")
        return

    try:
        is_admin = await user_is_group_admin(update, context)
    except Exception as e:
        await update.message.reply_text(f"Failed to verify admin permissions: {e}")
        logging.error(f"Error checking admin permissions: {e}")
        return

    if not is_admin:
        await update.message.reply_text("Only group admins can use `/set_streak`.")
        return

    if len(context.args) != 2:
        await update.message.reply_text(
            "Usage: `/set_streak <leetcode_username> <streak_number>`\n"
            "Example: `/set_streak neal_wu 7`"
        )
        return

    username_to_set = context.args[0].strip()

    try:
        streak_value = int(context.args[1])
    except ValueError:
        await update.message.reply_text(
            "Invalid streak number. It must be an integer.\n"
            "Usage: `/set_streak <leetcode_username> <streak_number>`"
        )
        return

    today_utc_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")

    try:
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM groups WHERE chat_id = ?", (update.message.chat_id,))
            if not cursor.fetchone():
                await update.message.reply_text("This group is not registered yet. Run `/register_group` first.")
                return

            cursor.execute(
                "SELECT display_name FROM group_tracked_users WHERE chat_id = ? AND leetcode_username = ?",
                (update.message.chat_id, username_to_set)
            )
            tracked_user = cursor.fetchone()

            if not tracked_user:
                await update.message.reply_text(
                    f"User '{username_to_set}' is not tracked in this group. Use `/list` to see tracked users."
                )
                return

            cursor.execute(
                """
                INSERT INTO user_streaks (leetcode_username, last_date, streak_value)
                VALUES (?, ?, ?)
                ON CONFLICT(leetcode_username)
                DO UPDATE SET last_date = excluded.last_date, streak_value = excluded.streak_value
                """,
                (username_to_set, today_utc_str, streak_value)
            )
            conn.commit()

        await update.message.reply_text(
            f"✅ Streak for '{tracked_user[0]}' ({username_to_set}) is set to {streak_value}."
        )
        logging.info(
            "Set streak for user '%s' to %s in chat %s by %s",
            username_to_set,
            streak_value,
            update.message.chat_id,
            update.message.from_user.username
        )
    except Exception as e:
        await update.message.reply_text(f"An error occurred while setting streak: {e}")
        logging.error(f"Error setting streak for user '{username_to_set}': {e}")

# --- Core Automation Logic ---

async def check_for_updates(context: ContextTypes.DEFAULT_TYPE):
    """
    This is now the **SILENT DATA COLLECTOR**.
    It runs every hour, finds newly solved problems for "today",
    and stores them in the `posted_today` and `problem_info` tables.
    IT DOES NOT SEND ANY NOTIFICATIONS.
    """
    logging.info("Job: Running DATA COLLECTION check...")
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # 1. Fetch all groups
    cursor.execute("SELECT chat_id FROM groups")
    groups = cursor.fetchall()
    if not groups:
        logging.info("Job: No groups registered. Skipping collection.")
        conn.close()
        return

    # 2. Determine "today" and "yesterday" (UTC) dates
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    today_utc_str = now_utc.strftime('%Y-%m-%d')
    yesterday_utc_str = (now_utc - datetime.timedelta(days=1)).strftime('%Y-%m-%d')

    for (chat_id,) in groups:
        cursor.execute(
            "SELECT leetcode_username, display_name FROM group_tracked_users WHERE chat_id = ?",
            (chat_id,)
        )
        users = cursor.fetchall()

        if not users:
            logging.info(f"Job: No users to track for group {chat_id}.")
            continue

        for user_row in users:
            username = user_row[0]
            logging.info(f"Job: Collecting data for user {username} (group {chat_id})...")

            try:
                submissions = fetch_recent_submissions(username, limit=15)
                if submissions is None:
                    continue

                for sub in submissions:
                    # 3. Check if the problem was solved "today"
                    timestamp = int(sub['timestamp'])
                    submit_time_utc = datetime.datetime.fromtimestamp(timestamp, tz=datetime.timezone.utc)
                    submit_date_str = submit_time_utc.strftime('%Y-%m-%d')

                    if submit_date_str != today_utc_str and submit_date_str != yesterday_utc_str:
                        break

                    problem_slug = sub['titleSlug']

                    # 4. Check if this problem was already recorded for "today"
                    cursor.execute(
                        "SELECT 1 FROM posted_today WHERE chat_id = ? AND leetcode_username = ? AND problem_slug = ? AND date_posted = ?",
                        (chat_id, username, problem_slug, submit_date_str)
                    )
                    if cursor.fetchone():
                        # Already recorded, skip
                        continue

                    # 5. If new, populate cache and record in the database
                    logging.info(f"Job: Found new submission for {username} (group {chat_id}): {problem_slug}")

                    # Fetch problem info (title/difficulty) to fill the cache
                    # This is needed later for reporting
                    get_or_fetch_problem_info(cursor, problem_slug)

                    # Record in the "posted_today" table
                    cursor.execute(
                        "INSERT INTO posted_today (chat_id, leetcode_username, problem_slug, date_posted) VALUES (?, ?, ?, ?)",
                        (chat_id, username, problem_slug, submit_date_str)
                    )

                conn.commit() # Save after each user

            except Exception as e:
                logging.error(f"Job: Error during data collection for {username} (group {chat_id}): {e}")
                conn.rollback() # On error, roll back this user's changes
                continue

    conn.close()
    logging.info("Job: DATA COLLECTION finished.")

async def generate_and_send_report(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    date_str: str,
    title_prefix: str,
    update_streaks: bool = True
) -> bool:
    """
    Builds a report for the given UTC date and sends it to the group.
    If update_streaks=False, streak counts are not changed.
    Returns 'True' if data was found, otherwise 'False'.
    """
    logging.info(f"Job: Generating report for date: {date_str}")
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # 1. Fetch all users (needed for list and ordering)
    cursor.execute(
        "SELECT leetcode_username, display_name FROM group_tracked_users WHERE chat_id = ? ORDER BY display_name",
        (chat_id,)
    )
    tracked_users = cursor.fetchall()

    if not tracked_users:
        logging.info("Job: No tracked users. No report sent.")
        conn.close()
        return False

    # 3. Fetch all data for the given date ('date_str') from the DB
    query = """
    SELECT
        gtu.leetcode_username,
        gtu.display_name,
        pi.title,
        pi.difficulty,
        pi.problem_slug
    FROM posted_today AS pt
    JOIN group_tracked_users AS gtu ON pt.chat_id = gtu.chat_id AND pt.leetcode_username = gtu.leetcode_username
    JOIN problem_info AS pi ON pt.problem_slug = pi.problem_slug
    WHERE pt.date_posted = ? AND pt.chat_id = ?
    ORDER BY gtu.display_name, pi.difficulty
    """

    try:
        cursor.execute(query, (date_str, chat_id))
        results = cursor.fetchall()
    except Exception as e:
        logging.error(f"Job: Failed to query database for report: {e}")
        conn.close()
        return False

    # 4. Build the message
    report_data = {}
    for username, display_name in tracked_users:
        report_data[username] = {
            "display_name": display_name,
            "submissions": []
        }

    for row in results:
        username, display_name, title, difficulty, slug = row
        report_data[username]["submissions"].append((difficulty, title, slug))

    solved_users = []
    sleepers = []

    for username, display_name in tracked_users:
        submissions = report_data[username]["submissions"]
        solved_in_group = len(submissions) > 0

        if update_streaks:
            # Streaks are global per user, so check whether the user solved on this date
            # in any tracked group before updating user_streaks.
            cursor.execute(
                "SELECT 1 FROM posted_today WHERE leetcode_username = ? AND date_posted = ? LIMIT 1",
                (username, date_str)
            )
            solved_anywhere_today = cursor.fetchone() is not None
            streak_value, show_streak = update_user_streak(
                cursor, username, date_str, solved_anywhere_today
            )
        else:
            streak_value, show_streak = get_current_user_streak(cursor, username)
        streak_label = format_streak_label(streak_value) if show_streak else ""
        display_with_streak = f"{display_name}{streak_label}"

        if solved_in_group:
            solved_users.append((display_with_streak, submissions, streak_value))
        else:
            sleepers.append((display_with_streak, streak_value))

    # Use the title_prefix and date_str parameters
    message_parts = []
    if solved_users:
        solved_users.sort(key=lambda item: item[2], reverse=True)
        message = f"<b>{date_str}: Азаматтар</b>\n"
        for display_name, submissions, _streak_value in solved_users:
            message += f"\n<b>{display_name}</b>:\n"
            for (difficulty, title, slug) in submissions:
                problem_url = f"https://leetcode.com/problems/{slug}/"
                diff_icon = "🟢" if difficulty == "Easy" else "🟠" if difficulty == "Medium" else "🔴"
                message += f"   {diff_icon} <a href='{problem_url}'>{title}</a>\n"
        message_parts.append(message)

    if sleepers:
        sleepers.sort(key=lambda item: item[1])
        message = f"<b>{date_str}: Уктап калгандар</b>\n"
        for display_name, _streak_value in sleepers:
            message += f"\n<b>{display_name}</b>\n"
        message_parts.append(message)

    message = "\n".join(message_parts)

    # 5. Send the message
    try:
        conn.commit()
        await context.bot.send_message(
            chat_id=chat_id,
            text=message,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True
        )
        logging.info(f"Job: Successfully sent report for {date_str} to group {chat_id}")
        conn.close()
        return True  # Message sent
    except Exception as e:
        logging.error(f"Job: Failed to send report to group {chat_id}: {e}")
        conn.close()
        return False

async def send_daily_report(context: ContextTypes.DEFAULT_TYPE):
    """
    This is the AUTOMATIC REPORT SENDER (UTC 15:00).
    It starts preparing the report for yesterday.
    """
    logging.info("Job: Running DAILY REPORT sender...")

    # Calculate yesterday's date
    yesterday_utc = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)
    yesterday_utc_str = yesterday_utc.strftime('%Y-%m-%d')

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT chat_id FROM groups")
    groups = cursor.fetchall()
    conn.close()

    # Call the main function with "Yesterday"
    for (chat_id,) in groups:
        await generate_and_send_report(context, chat_id, yesterday_utc_str, "Кечээки")

async def clear_daily_log(context: ContextTypes.DEFAULT_TYPE):
    """
    Runs daily and cleans up old data.
    For example, data older than 2 days.
    """
    logging.info("Job: Running daily cleanup...")
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    two_days_ago = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=2)
    two_days_ago_str = two_days_ago.strftime('%Y-%m-%d')

    try:
        cursor.execute("DELETE FROM posted_today WHERE date_posted < ?", (two_days_ago_str,))
        conn.commit()
        logging.info(f"Job: Cleaned up {cursor.rowcount} old entries from posted_today table.")
    except Exception as e:
        logging.error(f"Job: Failed to clear daily log: {e}")
    finally:
        conn.close()

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Logs unexpected update/job exceptions through application handler."""
    logging.error("Unhandled exception in update/job handler", exc_info=context.error)

def get_or_fetch_problem_info(db_cursor, problem_slug: str) -> (str, str):
    """
    Checks the database for problem info (difficulty, title).
    If not found, fetches it from the API and stores it.
    """
    # 1. Check the cache
    db_cursor.execute("SELECT difficulty, title FROM problem_info WHERE problem_slug = ?", (problem_slug,))
    result = db_cursor.fetchone()

    if result:
        return (result[0], result[1])  # (difficulty, title)

    # 2. Not in cache, fetch from API
    logging.info(f"Cache miss. Fetching info for {problem_slug} from API...")
    difficulty, title = fetch_problem_difficulty(problem_slug)

    if difficulty and title:
        # 3. Save to cache (database)
        try:
            db_cursor.execute("INSERT INTO problem_info (problem_slug, difficulty, title) VALUES (?, ?, ?)",
                              (problem_slug, difficulty, title))
            # conn.commit() is not called here; the caller commits
        except sqlite3.IntegrityError:
            pass # If another process already inserted it
        return (difficulty, title)
    else:
        return ("N/A", problem_slug) # If the API fails

def format_streak_label(streak_value: int) -> str:
    """Formats streak label for display."""
    if streak_value > 0:
        return f" (🔥 +{streak_value})"
    return f" (❄️ {streak_value})"

def get_current_user_streak(db_cursor, username: str) -> (int, bool):
    """
    Returns the current stored streak without mutating user_streaks.
    Returns (streak_value, show_streak_flag).
    """
    db_cursor.execute(
        "SELECT streak_value FROM user_streaks WHERE leetcode_username = ?",
        (username,)
    )
    row = db_cursor.fetchone()
    if not row:
        return 0, False
    return row[0], True

def update_user_streak(db_cursor, username: str, date_str: str, solved_today: bool) -> (int, bool):
    """
    Updates and returns user's streak for given date.
    Returns (streak_value, show_streak_flag).
    """
    db_cursor.execute(
        "SELECT last_date, streak_value FROM user_streaks WHERE leetcode_username = ?",
        (username,)
    )
    existing = db_cursor.fetchone()
    current_date = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()

    if not existing:
        new_streak = 1 if solved_today else -1
        db_cursor.execute(
            "INSERT INTO user_streaks (leetcode_username, last_date, streak_value) VALUES (?, ?, ?)",
            (username, date_str, new_streak)
        )
        return new_streak, True

    last_date_str, streak_value = existing
    try:
        last_date = datetime.datetime.strptime(last_date_str, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        # Self-heal legacy/corrupted date values (e.g. "$YESTERDAY_UTC")
        logging.warning(
            "Invalid streak date for user '%s': %r. Resetting streak from report date %s.",
            username,
            last_date_str,
            date_str
        )
        new_streak = 1 if solved_today else -1
        db_cursor.execute(
            "UPDATE user_streaks SET last_date = ?, streak_value = ? WHERE leetcode_username = ?",
            (date_str, new_streak, username)
        )
        return new_streak, True
    day_delta = (current_date - last_date).days

    if day_delta <= 0:
        return streak_value, True

    if day_delta != 1:
        new_streak = 1 if solved_today else -1
    elif solved_today:
        new_streak = streak_value + 1 if streak_value > 0 else 1
    else:
        new_streak = streak_value - 1 if streak_value < 0 else -1

    db_cursor.execute(
        "UPDATE user_streaks SET last_date = ?, streak_value = ? WHERE leetcode_username = ?",
        (date_str, new_streak, username)
    )
    return new_streak, True

def get_or_fetch_difficulty(db_cursor, problem_slug: str) -> str:
    """
    Checks the DB for a problem's difficulty.
    If not found, fetches from LeetCode API and saves it.
    """
    # 1. Check cache first
    db_cursor.execute("SELECT difficulty FROM problem_difficulty WHERE problem_slug = ?", (problem_slug,))
    result = db_cursor.fetchone()

    if result:
        return result[0]  # Return difficulty from cache

    # 2. Not in cache, fetch from API
    logging.info(f"Cache miss. Fetching difficulty for {problem_slug} from API...")
    difficulty = fetch_problem_difficulty(problem_slug)

    if difficulty:
        # 3. Save to cache (database)
        try:
            db_cursor.execute("INSERT INTO problem_difficulty (problem_slug, difficulty) VALUES (?, ?)",
                              (problem_slug, difficulty))
        except sqlite3.IntegrityError:
            pass  # Should not happen, but good to handle
        return difficulty
    else:
        return "N/A" # Default if API fails

# --- Main Bot Function ---

def main():
    """Starts the bot and schedules jobs."""
    if TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("!!! ERROR: Please replace 'YOUR_BOT_TOKEN_HERE' with your actual bot token.")
        return

    init_db()

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # --- JOB SCHEDULING ---
    job_queue = application.job_queue

    # 1. Data collection job (hourly)
    job_queue.run_repeating(check_for_updates, interval=CHECK_INTERVAL_SECONDS, first=10)

    # 2. Report sender job (daily at UTC 7:00)
    report_time = datetime.time(hour=7, minute=0, tzinfo=datetime.timezone.utc)
    job_queue.run_daily(send_daily_report, time=report_time)

    # 3. Cleanup job (daily at UTC 9:00, after the report)
    cleanup_time = datetime.time(hour=9, minute=0, tzinfo=datetime.timezone.utc)
    job_queue.run_daily(clear_daily_log, time=cleanup_time)

    logging.info(f"Scheduled data collection every {CHECK_INTERVAL_SECONDS} seconds.")
    logging.info(f"Scheduled daily report for {report_time} UTC.")
    logging.info(f"Scheduled daily cleanup for {cleanup_time} UTC.")

    # Register command handlers (no changes)
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("register_group", register_group_command))
    application.add_handler(CommandHandler("add", add_user_command))
    application.add_handler(CommandHandler("remove", remove_user_command))
    application.add_handler(CommandHandler("list", list_users_command))
    application.add_handler(CommandHandler("send_report", manual_send_report_command))
    application.add_handler(CommandHandler("send_today", manual_send_today_command))
    application.add_handler(CommandHandler("set_streak", set_streak_command))
    application.add_error_handler(error_handler)

    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO
    )

    print("Bot is starting... Press Ctrl+C to stop.")
    application.run_polling()

if __name__ == "__main__":
    main()