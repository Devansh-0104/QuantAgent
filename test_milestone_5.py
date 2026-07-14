import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy import inspect
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.database import Base
from database.migrate import migrate
from models.company import Company
from models.opportunity import Opportunity
from models.opportunity import OpportunityHistory
from models.opportunity import OpportunityStatus
from models.opportunity import OpportunityType
from models.page import Page
from models.page import PageType
from services.monitor import Monitor


class LifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine)

        setup = self.session_factory()
        company = Company(name="Example")
        setup.add(company)
        setup.flush()
        page = Page(
            company_id=company.id,
            page_type=PageType.CAREERS,
            url="https://example.com/careers",
        )
        setup.add(page)
        setup.commit()
        self.company_id = company.id
        self.page_id = page.id
        setup.close()

        with patch("services.monitor.SessionLocal", self.session_factory):
            self.monitor = Monitor()

    def tearDown(self) -> None:
        self.monitor.db.close()
        self.engine.dispose()

    def opportunity(self, **changes: object) -> dict[str, object]:
        item: dict[str, object] = {
            "company_id": self.company_id,
            "page_id": self.page_id,
            "provider_id": "provider-1",
            "type": OpportunityType.JOB,
            "title": "Quant Developer",
            "description": "Initial description",
            "location": "London",
            "url": "https://example.com/jobs/1",
            "visa": None,
            "deadline": None,
        }
        item.update(changes)
        return item

    def test_complete_lifecycle_records_history(self) -> None:
        created = self.monitor.reconcile_opportunities(
            self.page_id,
            [self.opportunity()],
        )
        self.assertEqual(created.new, 1)

        unchanged = self.monitor.reconcile_opportunities(
            self.page_id,
            [self.opportunity()],
        )
        self.assertEqual(unchanged.unchanged, 1)

        updated = self.monitor.reconcile_opportunities(
            self.page_id,
            [self.opportunity(description="Changed description")],
        )
        self.assertEqual(updated.updated, 1)

        closed = self.monitor.reconcile_opportunities(self.page_id, [])
        self.assertEqual(closed.closed, 1)

        reopened = self.monitor.reconcile_opportunities(
            self.page_id,
            [self.opportunity(description="Changed description")],
        )
        self.assertEqual(reopened.reopened, 1)

        opportunity = self.monitor.db.query(Opportunity).one()
        self.assertEqual(opportunity.status, OpportunityStatus.OPEN)
        self.assertEqual(opportunity.description, "Changed description")
        self.assertEqual(
            [history.event for history in self.monitor.db.query(OpportunityHistory).all()],
            ["NEW", "UPDATED", "CLOSED", "REOPENED"],
        )

    def test_provider_identity_survives_url_change(self) -> None:
        self.monitor.reconcile_opportunities(self.page_id, [self.opportunity()])
        original_id = self.monitor.db.query(Opportunity).one().id

        result = self.monitor.reconcile_opportunities(
            self.page_id,
            [self.opportunity(url="https://example.com/jobs/renamed")],
        )

        self.assertEqual(result.updated, 1)
        self.assertEqual(self.monitor.db.query(Opportunity).count(), 1)
        opportunity = self.monitor.db.query(Opportunity).one()
        self.assertEqual(opportunity.id, original_id)
        self.assertEqual(opportunity.url, "https://example.com/jobs/renamed")

    def test_failed_batch_rolls_back_without_closing_records(self) -> None:
        self.monitor.reconcile_opportunities(self.page_id, [self.opportunity()])

        invalid = self.opportunity()
        del invalid["type"]
        with self.assertRaises(KeyError):
            self.monitor.reconcile_opportunities(self.page_id, [invalid])

        opportunity = self.monitor.db.query(Opportunity).one()
        self.assertEqual(opportunity.status, OpportunityStatus.OPEN)
        self.assertEqual(
            self.monitor.db.query(OpportunityHistory).count(),
            1,
        )

    def test_incomplete_scan_does_not_close_unseen_records(self) -> None:
        self.monitor.reconcile_opportunities(self.page_id, [self.opportunity()])

        result = self.monitor.reconcile_opportunities(
            self.page_id,
            [],
            scan_completed=False,
        )

        self.assertEqual(result.closed, 0)
        opportunity = self.monitor.db.query(Opportunity).one()
        self.assertEqual(opportunity.status, OpportunityStatus.OPEN)

    def test_legacy_save_return_value_remains_new_count(self) -> None:
        added = self.monitor.save_opportunities(
            [self.opportunity()],
            page_id=self.page_id,
        )
        self.assertEqual(added, 1)


class MigrationTests(unittest.TestCase):
    def test_legacy_database_migration_is_idempotent(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        with engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE TABLE opportunities ("
                    "id INTEGER NOT NULL PRIMARY KEY, "
                    "company_id INTEGER NOT NULL, "
                    "page_id INTEGER NOT NULL, "
                    "type VARCHAR(11) NOT NULL, "
                    "title VARCHAR NOT NULL, "
                    "location VARCHAR, "
                    "url VARCHAR NOT NULL UNIQUE, "
                    "visa VARCHAR, "
                    "deadline VARCHAR, "
                    "hash VARCHAR, "
                    "first_seen DATETIME NOT NULL, "
                    "last_seen DATETIME NOT NULL"
                    ")"
                )
            )

        migrate(engine)
        migrate(engine)

        inspector = inspect(engine)
        columns = {
            column["name"] for column in inspector.get_columns("opportunities")
        }
        self.assertTrue(
            {
                "provider_id",
                "description",
                "status",
                "last_modified",
                "match_score",
                "match_priority",
                "match_reason",
            }
            <= columns
        )
        self.assertIn("opportunity_history", inspector.get_table_names())
        index_names = {
            index["name"] for index in inspector.get_indexes("opportunities")
        }
        self.assertIn("ix_opportunities_company_provider_id", index_names)
        history_index_names = {
            index["name"]
            for index in inspector.get_indexes("opportunity_history")
        }
        self.assertIn(
            "ix_opportunity_history_opportunity_id",
            history_index_names,
        )
        engine.dispose()


if __name__ == "__main__":
    unittest.main()
