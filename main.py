from app.config import DATA_DIR, LOG_DIR
from app.database import Base
from app.database import engine
import models.company
import models.page
import models.opportunity
from app.cli import app

Base.metadata.create_all(bind=engine)

app()