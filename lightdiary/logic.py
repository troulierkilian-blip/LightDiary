"""Pure statistics and supportive, offline copy."""
from datetime import date, datetime, timedelta


def display_weight(value, unit="kg"):
    return "—" if value is None else f"{value * (2 if unit == 'jin' else 1):.1f}"


def progress(start, target, current):
    if any(value is None for value in (start, target, current)):
        return 0
    if start == target:
        return 100 if current <= target else 0
    return max(0, min(100, round((start - current) / (start - target) * 100)))


def weekly_stats(rows, end=None):
    end = end or date.today()
    first = end - timedelta(days=6)
    current = [row for row in rows if first.isoformat() <= row["day"] <= end.isoformat()]
    weights = [row["weight_kg"] for row in current if row["weight_kg"] is not None]
    previous = [row["weight_kg"] for row in rows if (first - timedelta(days=7)).isoformat() <= row["day"] < first.isoformat() and row["weight_kg"] is not None]
    average = sum(weights) / len(weights) if weights else None
    difference = average - sum(previous) / len(previous) if len(weights) >= 2 and len(previous) >= 2 else None
    return {"average": average, "difference": difference, "weight_days": len(weights), "record_days": len(current),
            "minutes": sum(row["minutes"] or 0 for row in current), "activity_days": sum(bool(row["activity"] or row["minutes"]) for row in current)}


def encouragement(rows, completed_count=0, today=None):
    today = today or date.today()
    if not rows:
        return "从今天的一小步开始", "写下一项就很好：一顿饭、一次活动，或者今天的体重。"
    last = date.fromisoformat(rows[-1]["day"])
    if last < today - timedelta(days=2):
        return "欢迎回来，今天可以重新开始", "过去的空白不需要补偿。记下今天的一件事，就继续向前了。"
    if completed_count:
        return f"今天已经照顾了自己 {completed_count} 次", "每个完成的小目标都值得肯定。让适合自己的节奏慢慢成为习惯。"
    if len(rows) == 1:
        return "第一步已经留下来了", "你已经开始了解自己的日常。明天再记一点，变化会慢慢清晰。"
    recent = sum(row["day"] >= (today - timedelta(days=6)).isoformat() for row in rows)
    return f"这周你留下了 {recent} 天的记录", "每天的数字会变化。看看一周的趋势，也看看你已经做到的事情。"


def reminder_due(settings, now: datetime, already_sent=False, paused=False):
    if not settings.get("onboarded") or not settings.get("reminder_enabled") or paused or already_sent:
        return False
    try:
        hour, minute = map(int, settings["reminder_time"].split(":"))
        scheduled = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    except (ValueError, KeyError):
        return False
    # A short window avoids a burst of old reminders after waking the computer.
    return 0 <= (now - scheduled).total_seconds() < 600
