from app.config import DATA_DIR, LOG_DIR
from app.database import Base
from app.database import engine
from database.migrate import migrate
import models.company
import models.notification
import models.page
import models.opportunity
from app.cli import app


def main() -> None:
    Base.metadata.create_all(bind=engine)
    migrate(engine)
    app()


if __name__ == "__main__":
    main()
