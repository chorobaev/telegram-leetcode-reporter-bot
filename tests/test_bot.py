import datetime
import os
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")

import bot


def make_update(chat_id=1, chat_type="group", username="tester", user_id=111):
    message = SimpleNamespace(
        chat_id=chat_id,
        chat=SimpleNamespace(type=chat_type),
        from_user=SimpleNamespace(username=username, id=user_id),
        reply_text=AsyncMock(),
    )
    return SimpleNamespace(message=message)


class DatabaseTestMixin:
    def setUp(self):
        self._temp_dir = tempfile.TemporaryDirectory()
        self._original_db_name = bot.DB_NAME
        bot.DB_NAME = os.path.join(self._temp_dir.name, "test.db")
        bot.init_db()

    def tearDown(self):
        bot.DB_NAME = self._original_db_name
        self._temp_dir.cleanup()

    def connect(self):
        return sqlite3.connect(bot.DB_NAME)


class TestStreakLogic(DatabaseTestMixin, unittest.TestCase):
    def test_new_user_streak_created_with_visible_label(self):
        with self.connect() as conn:
            cursor = conn.cursor()
            streak_value, show_label = bot.update_user_streak(
                cursor, "alice", "2026-02-10", True
            )
            conn.commit()

            cursor.execute(
                "SELECT last_date, streak_value FROM user_streaks WHERE leetcode_username = ?",
                ("alice",),
            )
            db_row = cursor.fetchone()

        self.assertEqual(streak_value, 1)
        self.assertTrue(show_label)
        self.assertEqual(db_row, ("2026-02-10", 1))

    def test_streak_advances_and_flips_to_negative_after_miss(self):
        with self.connect() as conn:
            cursor = conn.cursor()
            bot.update_user_streak(cursor, "alice", "2026-02-10", True)
            day2_value, day2_show = bot.update_user_streak(
                cursor, "alice", "2026-02-11", True
            )
            day3_value, day3_show = bot.update_user_streak(
                cursor, "alice", "2026-02-12", False
            )
            conn.commit()

            cursor.execute(
                "SELECT last_date, streak_value FROM user_streaks WHERE leetcode_username = ?",
                ("alice",),
            )
            db_row = cursor.fetchone()

        self.assertEqual((day2_value, day2_show), (2, True))
        self.assertEqual((day3_value, day3_show), (-1, True))
        self.assertEqual(db_row, ("2026-02-12", -1))

    def test_non_consecutive_day_resets_streak(self):
        with self.connect() as conn:
            cursor = conn.cursor()
            bot.update_user_streak(cursor, "alice", "2026-02-10", True)
            reset_value, show_label = bot.update_user_streak(
                cursor, "alice", "2026-02-15", False
            )
            conn.commit()

        self.assertEqual((reset_value, show_label), (-1, True))

    def test_invalid_streak_date_self_heals_instead_of_crashing(self):
        with self.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO user_streaks (leetcode_username, last_date, streak_value) VALUES (?, ?, ?)",
                ("alice", "$YESTERDAY_UTC", 12),
            )

            streak_value, show_label = bot.update_user_streak(
                cursor, "alice", "2026-02-15", True
            )
            conn.commit()

            cursor.execute(
                "SELECT last_date, streak_value FROM user_streaks WHERE leetcode_username = ?",
                ("alice",),
            )
            db_row = cursor.fetchone()

        self.assertEqual((streak_value, show_label), (1, True))
        self.assertEqual(db_row, ("2026-02-15", 1))


class TestProblemInfoCache(DatabaseTestMixin, unittest.TestCase):
    def test_cache_hit_skips_api_fetch(self):
        with self.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO problem_info (problem_slug, difficulty, title) VALUES (?, ?, ?)",
                ("two-sum", "Easy", "Two Sum"),
            )
            conn.commit()

            with patch("bot.fetch_problem_difficulty") as fetch_mock:
                result = bot.get_or_fetch_problem_info(cursor, "two-sum")

        self.assertEqual(result, ("Easy", "Two Sum"))
        fetch_mock.assert_not_called()

    def test_cache_miss_fetches_and_persists(self):
        with self.connect() as conn:
            cursor = conn.cursor()
            with patch(
                "bot.fetch_problem_difficulty", return_value=("Medium", "Three Sum")
            ) as fetch_mock:
                result = bot.get_or_fetch_problem_info(cursor, "3sum")
            conn.commit()

            cursor.execute(
                "SELECT difficulty, title FROM problem_info WHERE problem_slug = ?",
                ("3sum",),
            )
            db_row = cursor.fetchone()

        self.assertEqual(result, ("Medium", "Three Sum"))
        self.assertEqual(db_row, ("Medium", "Three Sum"))
        fetch_mock.assert_called_once_with("3sum")

    def test_api_failure_falls_back_to_slug(self):
        with self.connect() as conn:
            cursor = conn.cursor()
            with patch("bot.fetch_problem_difficulty", return_value=(None, None)):
                result = bot.get_or_fetch_problem_info(cursor, "missing-problem")

        self.assertEqual(result, ("N/A", "missing-problem"))


class TestCommandHandlers(DatabaseTestMixin, unittest.IsolatedAsyncioTestCase):
    async def test_register_group_rejects_private_chats(self):
        update = make_update(chat_id=10, chat_type="private")

        await bot.register_group_command(update, SimpleNamespace())

        update.message.reply_text.assert_awaited_once()
        reply_text = update.message.reply_text.await_args.args[0]
        self.assertIn("inside the Telegram group", reply_text)

    async def test_add_list_remove_flow_for_registered_group(self):
        register_update = make_update(chat_id=555, chat_type="group")
        await bot.register_group_command(register_update, SimpleNamespace())

        add_update = make_update(chat_id=555, chat_type="group")
        await bot.add_user_command(
            add_update, SimpleNamespace(args=["alice", "Alice", "A."])
        )
        add_reply = add_update.message.reply_text.await_args.args[0]
        self.assertIn("is now being tracked", add_reply)

        list_update = make_update(chat_id=555, chat_type="group")
        await bot.list_users_command(list_update, SimpleNamespace(args=[]))
        list_reply = list_update.message.reply_text.await_args.args[0]
        self.assertIn("Alice A. (alice)", list_reply)

        remove_update = make_update(chat_id=555, chat_type="group")
        await bot.remove_user_command(remove_update, SimpleNamespace(args=["alice"]))
        remove_reply = remove_update.message.reply_text.await_args.args[0]
        self.assertIn("has been removed", remove_reply)

        with self.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM group_tracked_users WHERE chat_id = ?",
                (555,),
            )
            remaining = cursor.fetchone()[0]

        self.assertEqual(remaining, 0)

    async def test_add_user_requires_registered_group(self):
        update = make_update(chat_id=42, chat_type="group")

        await bot.add_user_command(update, SimpleNamespace(args=["bob", "Bob"]))

        update.message.reply_text.assert_awaited_once()
        reply_text = update.message.reply_text.await_args.args[0]
        self.assertIn("not registered yet", reply_text)

    async def test_manual_send_report_does_not_update_streaks(self):
        with self.connect() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO groups (chat_id) VALUES (?)", (7001,))
            conn.commit()

        update = make_update(chat_id=7001, chat_type="group")

        with patch(
            "bot.generate_and_send_report", new=AsyncMock(return_value=True)
        ) as report_mock:
            await bot.manual_send_report_command(update, SimpleNamespace())

        report_mock.assert_awaited_once()
        self.assertFalse(report_mock.await_args.kwargs["update_streaks"])

    async def test_manual_send_today_does_not_update_streaks(self):
        with self.connect() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO groups (chat_id) VALUES (?)", (7002,))
            conn.commit()

        update = make_update(chat_id=7002, chat_type="group")

        with patch(
            "bot.generate_and_send_report", new=AsyncMock(return_value=True)
        ) as report_mock:
            await bot.manual_send_today_command(update, SimpleNamespace())

        report_mock.assert_awaited_once()
        self.assertFalse(report_mock.await_args.kwargs["update_streaks"])

    async def test_set_streak_rejects_non_admin(self):
        with self.connect() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO groups (chat_id) VALUES (?)", (7003,))
            cursor.execute(
                "INSERT INTO group_tracked_users (chat_id, leetcode_username, display_name) VALUES (?, ?, ?)",
                (7003, "alice", "Alice"),
            )
            conn.commit()

        update = make_update(chat_id=7003, chat_type="group", user_id=222)
        context = SimpleNamespace(
            args=["alice", "3"],
            bot=SimpleNamespace(
                get_chat_member=AsyncMock(return_value=SimpleNamespace(status="member"))
            ),
        )

        await bot.set_streak_command(update, context)

        denied_reply = update.message.reply_text.await_args.args[0]
        self.assertIn("Only group admins can use", denied_reply)
        context.bot.get_chat_member.assert_awaited_once_with(chat_id=7003, user_id=222)

        with self.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM user_streaks WHERE leetcode_username = ?",
                ("alice",),
            )
            row_count = cursor.fetchone()[0]

        self.assertEqual(row_count, 0)

    async def test_set_streak_admin_updates_existing_streak_with_today_utc(self):
        with self.connect() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO groups (chat_id) VALUES (?)", (7004,))
            cursor.execute(
                "INSERT INTO group_tracked_users (chat_id, leetcode_username, display_name) VALUES (?, ?, ?)",
                (7004, "alice", "Alice"),
            )
            cursor.execute(
                "INSERT INTO user_streaks (leetcode_username, last_date, streak_value) VALUES (?, ?, ?)",
                ("alice", "2026-01-01", 1),
            )
            conn.commit()

        update = make_update(chat_id=7004, chat_type="group", user_id=333)
        context = SimpleNamespace(
            args=["alice", "12"],
            bot=SimpleNamespace(
                get_chat_member=AsyncMock(
                    return_value=SimpleNamespace(status="administrator")
                )
            ),
        )

        await bot.set_streak_command(update, context)

        success_reply = update.message.reply_text.await_args.args[0]
        self.assertIn("is set to 12", success_reply)
        context.bot.get_chat_member.assert_awaited_once_with(chat_id=7004, user_id=333)

        today_utc_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
        with self.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT last_date, streak_value FROM user_streaks WHERE leetcode_username = ?",
                ("alice",),
            )
            streak_row = cursor.fetchone()

        self.assertEqual(streak_row, (today_utc_str, 12))

    async def test_set_streak_rejects_untracked_user_in_group(self):
        with self.connect() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO groups (chat_id) VALUES (?)", (7005,))
            cursor.execute(
                "INSERT INTO group_tracked_users (chat_id, leetcode_username, display_name) VALUES (?, ?, ?)",
                (7005, "alice", "Alice"),
            )
            conn.commit()

        update = make_update(chat_id=7005, chat_type="group", user_id=444)
        context = SimpleNamespace(
            args=["bob", "5"],
            bot=SimpleNamespace(
                get_chat_member=AsyncMock(
                    return_value=SimpleNamespace(status="administrator")
                )
            ),
        )

        await bot.set_streak_command(update, context)

        untracked_reply = update.message.reply_text.await_args.args[0]
        self.assertIn("is not tracked in this group", untracked_reply)

        with self.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM user_streaks WHERE leetcode_username = ?",
                ("bob",),
            )
            row_count = cursor.fetchone()[0]

        self.assertEqual(row_count, 0)

    async def test_set_streak_requires_both_username_and_number(self):
        update = make_update(chat_id=7006, chat_type="group", user_id=555)
        context = SimpleNamespace(
            args=["alice"],
            bot=SimpleNamespace(
                get_chat_member=AsyncMock(
                    return_value=SimpleNamespace(status="administrator")
                )
            ),
        )

        await bot.set_streak_command(update, context)

        usage_reply = update.message.reply_text.await_args.args[0]
        self.assertIn("Usage: `/set_streak <leetcode_username> <streak_number>`", usage_reply)

    async def test_set_streak_rejects_non_integer_streak_value(self):
        update = make_update(chat_id=7007, chat_type="group", user_id=666)
        context = SimpleNamespace(
            args=["alice", "abc"],
            bot=SimpleNamespace(
                get_chat_member=AsyncMock(
                    return_value=SimpleNamespace(status="administrator")
                )
            ),
        )

        await bot.set_streak_command(update, context)

        invalid_reply = update.message.reply_text.await_args.args[0]
        self.assertIn("must be an integer", invalid_reply)

    async def test_set_streak_rejects_private_chat(self):
        update = make_update(chat_id=7008, chat_type="private", user_id=777)
        context = SimpleNamespace(
            args=["alice", "4"],
            bot=SimpleNamespace(get_chat_member=AsyncMock()),
        )

        await bot.set_streak_command(update, context)

        private_reply = update.message.reply_text.await_args.args[0]
        self.assertIn("inside your group", private_reply)
        context.bot.get_chat_member.assert_not_awaited()

    async def test_set_streak_handles_admin_check_failure(self):
        update = make_update(chat_id=7009, chat_type="group", user_id=888)
        context = SimpleNamespace(
            args=["alice", "4"],
            bot=SimpleNamespace(
                get_chat_member=AsyncMock(side_effect=RuntimeError("telegram unavailable"))
            ),
        )

        await bot.set_streak_command(update, context)

        permission_reply = update.message.reply_text.await_args.args[0]
        self.assertIn("Failed to verify admin permissions", permission_reply)
        context.bot.get_chat_member.assert_awaited_once_with(chat_id=7009, user_id=888)

    async def test_set_streak_rejects_unregistered_group(self):
        update = make_update(chat_id=7010, chat_type="group", user_id=999)
        context = SimpleNamespace(
            args=["alice", "5"],
            bot=SimpleNamespace(
                get_chat_member=AsyncMock(
                    return_value=SimpleNamespace(status="administrator")
                )
            ),
        )

        await bot.set_streak_command(update, context)

        unregistered_reply = update.message.reply_text.await_args.args[0]
        self.assertIn("group is not registered yet", unregistered_reply)

        with self.connect() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM user_streaks")
            row_count = cursor.fetchone()[0]

        self.assertEqual(row_count, 0)


class TestCollectorAndReports(DatabaseTestMixin, unittest.IsolatedAsyncioTestCase):
    async def test_check_for_updates_inserts_only_new_todays_submissions(self):
        with self.connect() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO groups (chat_id) VALUES (?)", (1001,))
            cursor.execute(
                "INSERT INTO group_tracked_users (chat_id, leetcode_username, display_name) VALUES (?, ?, ?)",
                (1001, "alice", "Alice"),
            )
            conn.commit()

        now_utc = datetime.datetime.now(datetime.timezone.utc)
        submissions = [
            {"timestamp": str(int(now_utc.timestamp())), "titleSlug": "two-sum"},
            {
                "timestamp": str(
                    int((now_utc - datetime.timedelta(days=1)).timestamp())
                ),
                "titleSlug": "old-problem",
            },
        ]

        with patch("bot.fetch_recent_submissions", return_value=submissions), patch(
            "bot.get_or_fetch_problem_info", return_value=("Easy", "Two Sum")
        ) as problem_info_mock:
            await bot.check_for_updates(SimpleNamespace())
            await bot.check_for_updates(SimpleNamespace())

        with self.connect() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM posted_today")
            total_rows = cursor.fetchone()[0]
            cursor.execute("SELECT problem_slug FROM posted_today")
            slug_rows = [row[0] for row in cursor.fetchall()]

        self.assertEqual(total_rows, 1)
        self.assertEqual(slug_rows, ["two-sum"])
        self.assertEqual(problem_info_mock.call_count, 1)

    async def test_generate_report_uses_global_streak_signal_across_groups(self):
        report_date = "2026-02-10"
        with self.connect() as conn:
            cursor = conn.cursor()
            cursor.executemany(
                "INSERT INTO group_tracked_users (chat_id, leetcode_username, display_name) VALUES (?, ?, ?)",
                [
                    (1, "alice", "Alice"),
                    (2, "alice", "Alice"),
                ],
            )
            cursor.execute(
                "INSERT INTO problem_info (problem_slug, difficulty, title) VALUES (?, ?, ?)",
                ("two-sum", "Easy", "Two Sum"),
            )
            cursor.execute(
                "INSERT INTO posted_today (chat_id, leetcode_username, problem_slug, date_posted) VALUES (?, ?, ?, ?)",
                (2, "alice", "two-sum", report_date),
            )
            conn.commit()

        send_message_mock = AsyncMock()
        context = SimpleNamespace(bot=SimpleNamespace(send_message=send_message_mock))

        result = await bot.generate_and_send_report(context, 1, report_date, "Today")

        self.assertTrue(result)
        send_message_mock.assert_awaited_once()
        sent_text = send_message_mock.await_args.kwargs["text"]
        self.assertIn("Уктап калгандар", sent_text)
        self.assertNotIn("Азаматтар", sent_text)
        self.assertIn("<b>Alice (🔥 +1)</b>", sent_text)

        with self.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT last_date, streak_value FROM user_streaks WHERE leetcode_username = ?",
                ("alice",),
            )
            streak_row = cursor.fetchone()

        self.assertEqual(streak_row, (report_date, 1))

    async def test_generate_report_can_skip_streak_mutation(self):
        report_date = "2026-02-10"
        with self.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO group_tracked_users (chat_id, leetcode_username, display_name) VALUES (?, ?, ?)",
                (1, "alice", "Alice"),
            )
            cursor.execute(
                "INSERT INTO problem_info (problem_slug, difficulty, title) VALUES (?, ?, ?)",
                ("two-sum", "Easy", "Two Sum"),
            )
            cursor.execute(
                "INSERT INTO posted_today (chat_id, leetcode_username, problem_slug, date_posted) VALUES (?, ?, ?, ?)",
                (1, "alice", "two-sum", report_date),
            )
            cursor.execute(
                "INSERT INTO user_streaks (leetcode_username, last_date, streak_value) VALUES (?, ?, ?)",
                ("alice", "2026-02-09", 5),
            )
            conn.commit()

        send_message_mock = AsyncMock()
        context = SimpleNamespace(bot=SimpleNamespace(send_message=send_message_mock))

        result = await bot.generate_and_send_report(
            context, 1, report_date, "Today", update_streaks=False
        )

        self.assertTrue(result)
        send_message_mock.assert_awaited_once()

        with self.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT last_date, streak_value FROM user_streaks WHERE leetcode_username = ?",
                ("alice",),
            )
            streak_row = cursor.fetchone()

        self.assertEqual(streak_row, ("2026-02-09", 5))

    async def test_generate_report_with_solved_user_sends_problem_links(self):
        report_date = "2026-02-10"
        with self.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO group_tracked_users (chat_id, leetcode_username, display_name) VALUES (?, ?, ?)",
                (1, "bob", "Bob"),
            )
            cursor.execute(
                "INSERT INTO problem_info (problem_slug, difficulty, title) VALUES (?, ?, ?)",
                ("two-sum", "Easy", "Two Sum"),
            )
            cursor.execute(
                "INSERT INTO posted_today (chat_id, leetcode_username, problem_slug, date_posted) VALUES (?, ?, ?, ?)",
                (1, "bob", "two-sum", report_date),
            )
            conn.commit()

        send_message_mock = AsyncMock()
        context = SimpleNamespace(bot=SimpleNamespace(send_message=send_message_mock))

        result = await bot.generate_and_send_report(context, 1, report_date, "Today")

        self.assertTrue(result)
        send_message_mock.assert_awaited_once()
        sent_text = send_message_mock.await_args.kwargs["text"]
        self.assertIn("Азаматтар", sent_text)
        self.assertIn("<b>Bob (🔥 +1)</b>", sent_text)
        self.assertIn(
            "🟢 <a href='https://leetcode.com/problems/two-sum/'>Two Sum</a>",
            sent_text,
        )

    async def test_generate_report_returns_false_when_group_has_no_tracked_users(self):
        send_message_mock = AsyncMock()
        context = SimpleNamespace(bot=SimpleNamespace(send_message=send_message_mock))

        result = await bot.generate_and_send_report(
            context, chat_id=999, date_str="2026-02-10", title_prefix="Today"
        )

        self.assertFalse(result)
        send_message_mock.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
