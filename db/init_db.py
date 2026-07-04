import os
import sys
import sqlite3
import pathlib

# Add project root to sys.path to resolve imports correctly
project_root = pathlib.Path(__file__).parent.parent.resolve()
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

import config

def init_db(db_target=config.DB_PATH):
    """
    Initializes the database by executing schema.sql.
    db_target can be a file path string or a sqlite3.Connection object.
    """
    schema_path = pathlib.Path(__file__).parent / "schema.sql"
    with open(schema_path, "r", encoding="utf-8") as f:
        ddl = f.read()
        
    if isinstance(db_target, sqlite3.Connection):
        db_target.executescript(ddl)
        db_target.commit()
    else:
        if db_target != ":memory:":
            pathlib.Path(db_target).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_target)
        try:
            conn.executescript(ddl)
            conn.commit()
        finally:
            conn.close()

if __name__ == "__main__":
    print(f"Initializing database at: {config.DB_PATH}")
    init_db()
    print("Database initialized successfully.")
