"""Apply numbered SQL files once. Recorded in schema_migrations."""

from pathlib import Path

from app.models.queries import SQL

MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations"


def statements(script: str) -> list[str]:
    parts: list[str] = []
    buffer: list[str] = []
    for line in script.splitlines():
        if line.strip().startswith("--"):
            continue
        buffer.append(line)
        if line.rstrip().endswith(";"):
            text = "\n".join(buffer).strip().rstrip(";").strip()
            if text:
                parts.append(text)
            buffer = []
    return parts


async def apply(pg) -> None:
    """Run any migration file that is not yet recorded. Safe to call on every startup."""
    await pg.execute(SQL.ENSURE_MIGRATIONS)
    done = {row[0] for row in await pg.fetch(SQL.APPLIED_MIGRATIONS)}
    for path in sorted(MIGRATIONS.glob("*.sql")):
        if path.name in done:
            continue
        await pg.execute_script(statements(path.read_text(encoding="utf-8")))
        await pg.execute(SQL.RECORD_MIGRATION, (path.name,))
