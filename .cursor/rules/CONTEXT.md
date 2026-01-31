---
description: Project context for the LeetCode Telegram reporter bot
alwaysApply: true
---

Project Context: LeetCode Telegram Reporter Bot
1. Project Overview
This is a Python-based Telegram bot that tracks LeetCode problem-solving activity for a specific group of users. It features a "silent collection" architecture where data is gathered periodically, but reports are sent as a consolidated summary once a day or upon manual command.

Core Philosophy
Consolidation: Avoid spamming the group. One message per day/request.

Data Integrity: Use SQLite as a local cache for problem metadata and user performance to minimize API calls.

Visibility: Provide clear reports on who solved which problems, including difficulty levels and contest rankings.

2. Tech Stack
Language: Python 3.10+

Library: python-telegram-bot (v22.5) with JobQueue support

HTTP: requests (Session + headers for LeetCode API)

API: LeetCode GraphQL API (https://leetcode.com/graphql)

Database: SQLite (sqlite3)

Deployment: Ubuntu Linux service (systemd)

3. Database Schema (leetcode_bot.db)
tracked_users: Stores mapping of LeetCode IDs to nicknames.

leetcode_username (PK), display_name

groups: Stores the target Telegram group ID.

chat_id (PK)

posted_today: Logs specific problems solved by a user on a specific date.

leetcode_username, problem_slug, date_posted (Format: YYYY-MM-DD)

problem_info: Cache for problem metadata.

problem_slug (PK), difficulty, title

4. File Structure & Responsibilities
bot.py (Main Logic)
Entry Point: main() initializes the Application and JobQueue.

Command Handlers: Handles /start, /help, /add, /remove, /list, /register_group, /send_report, /send_today.

Background Jobs:

check_for_updates: Runs every 1 hour. Performs silent data collection into posted_today.

send_daily_report: Runs at 07:00 UTC. Generates the summary for the previous day.

clear_daily_log: Runs daily at 09:00 UTC. Removes posted_today entries older than 2 days.

Reporting Engine: generate_and_send_report aggregates data from posted_today and tracked_users to create a formatted HTML message.

leetcode_api.py (API Interface)
GraphQL Queries: Contains string templates for getRecentAcSubmissionList and questionData.

Functions:

fetch_recent_submissions: Gets the latest accepted submissions for a user.

fetch_problem_difficulty: Gets metadata (title/difficulty) for a specific problem.

fetch_contest_performance: Fetches specific ranking and "solved: Q1, Q2" data for a contest slug.

5. Critical Logic Flow
The Reporting Loop
Note: All timing is based on UTC+0. LeetCode timestamps are Unix UTC.

Collection: check_for_updates looks for AC submissions where timestamp_date == today_utc and writes to posted_today + problem_info.

Reporting: When generating a report for date_X:

Fetch the group chat_id from groups.

Query posted_today + tracked_users + problem_info for date_X.

Format report with problem links and difficulty icons, grouped by display_name.

6. Environment Variables
TELEGRAM_BOT_TOKEN: Required for bot authentication. Managed via os.environ.

7. Development Patterns for AI Agents
DB Transactions: Use conn.commit() after per-user updates in check_for_updates; rollback on per-user failure.

Caching: Use problem_info to avoid repeat API calls for difficulty/title.

API Resilience: Use requests.Session() with a browser-like User-Agent and Referer to reduce 403/429.

HTML Formatting: Telegram messages use ParseMode.HTML. Ensure links are formatted as <a href="...">Title</a>.

Error Handling: Wrap API calls in try-except blocks to prevent the JobQueue from stalling.