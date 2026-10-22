"""Seed the messages table with random inbox messages for user 1 (admin).

Creates 10 randomly generated messages addressed to admin on each run.
Senders are picked from other existing users; if no other users exist,
messages are created as system messages (from_idu NULL).

Run: uv run python -m tools.seed_inbox
"""

from __future__ import annotations

import asyncio
import logging
import random
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.message import Message
from app.models.user import User

logger = logging.getLogger(__name__)

RECIPIENT_IDU = 1  # admin user seeded by tools.seed_users
COUNT = 10

SUBJECTS = [
    "Case approval pending",
    "Your task is overdue",
    "Subprocess completed successfully",
    "New case assigned to you",
    "Reminder: review due today",
    "Document uploaded for case #42",
    "Workflow instance paused",
    "Signal received from external system",
    "Case escalated to supervisor",
    "Monthly report ready",
]

BODIES = [
    "A new task has been assigned to you in the workflow. Please review at your earliest convenience.",
    "The case you are following reached a decision gateway and is awaiting your approval.",
    "An automated job finished running; results have been attached to the case record.",
    "Your pending task passed its due date without action. It has been flagged for follow-up.",
    "A subprocess instance completed all of its internal tasks. The parent case can proceed.",
    "The sender uploaded a document to the shared file store and linked it to your open case.",
    "An external system sent a signal that matched this workflow. No action required unless instructed otherwise.",
    "This case was escalated because no assignee responded within the SLA window.",
    "Scheduled report for this period is ready in the dashboard exports folder.",
    "The workflow instance has been paused by an administrator. It will resume once unpaused.",
]

TAGS = ["approval", "overdue", "report", None, None]  # weighted: tags are optional


def _random_checkdate() -> datetime:
    """Random timestamp within the last 30 days (UTC-aware)."""
    now = datetime.now(UTC)
    offset = timedelta(
        days=random.randint(0, 29),
        hours=random.randint(1, 23),
        minutes=random.randint(0, 59),
    )
    return now - offset


async def seed(db: AsyncSession) -> None:
    recipient = (
        await db.execute(select(User).where(User.idu == RECIPIENT_IDU))
    ).scalar_one_or_none()
    if recipient is None:
        raise SystemExit(
            f"[seed] Recipient user idu={RECIPIENT_IDU} not found — "
            f"run 'uv run python -m tools.seed_users' first"
        )

    senders = (
        (await db.execute(select(User).where(User.idu != RECIPIENT_IDU)))
        .scalars()
        .all()
    )
    sender_ids = [s.idu for s in senders] or [None]  # None → system message

    created: list[Message] = []
    for _ in range(COUNT):
        msg = Message(
            to_idu=RECIPIENT_IDU,
            from_idu=random.choice(sender_ids),
            subject=random.choice(SUBJECTS),
            body=random.choice(BODIES),
            folder="inbox",
            is_read=random.random() < 0.3,
            is_starred=random.random() < 0.2,
            tag=random.choice(TAGS),
            checkdate=_random_checkdate(),
        )
        db.add(msg)
        created.append(msg)

    await db.flush()

    for msg in created:
        sender = f"idu={msg.from_idu}" if msg.from_idu is not None else "system"
        print(
            f"[seed] idmessage={msg.idmessage} from={sender} "
            f"read={msg.is_read} starred={msg.is_starred} tag={msg.tag!r} "
            f"'{msg.subject}'"
        )


async def main() -> None:
    from extensions import async_session_factory

    async with async_session_factory() as db:
        await seed(db)
        await db.commit()

    print(f"[seed] {COUNT} random inbox messages seeded for user idu={RECIPIENT_IDU}")


if __name__ == "__main__":
    asyncio.run(main())
