from sqlalchemy import Engine
from sqlalchemy import inspect
from sqlalchemy import text


OPPORTUNITY_COLUMNS = {
    "provider_id": "VARCHAR",
    "description": "TEXT",
    "status": "VARCHAR(7) NOT NULL DEFAULT 'OPEN'",
    "last_modified": "DATETIME",
}


def migrate(engine: Engine) -> None:
    inspector = inspect(engine)
    if "opportunities" not in inspector.get_table_names():
        return

    existing_columns = {
        column["name"] for column in inspector.get_columns("opportunities")
    }

    with engine.begin() as connection:
        for column_name, definition in OPPORTUNITY_COLUMNS.items():
            if column_name not in existing_columns:
                connection.execute(
                    text(
                        f"ALTER TABLE opportunities "
                        f"ADD COLUMN {column_name} {definition}"
                    )
                )

        connection.execute(
            text(
                "UPDATE opportunities "
                "SET last_modified = COALESCE(last_modified, last_seen, first_seen)"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS "
                "ix_opportunities_company_provider_id "
                "ON opportunities (company_id, provider_id)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS opportunity_history ("
                "id INTEGER NOT NULL PRIMARY KEY, "
                "opportunity_id INTEGER NOT NULL, "
                "event VARCHAR NOT NULL, "
                "snapshot TEXT NOT NULL, "
                "created_at DATETIME NOT NULL, "
                "FOREIGN KEY(opportunity_id) REFERENCES opportunities (id)"
                ")"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS "
                "ix_opportunity_history_opportunity_id "
                "ON opportunity_history (opportunity_id)"
            )
        )
