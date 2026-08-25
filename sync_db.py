import os
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

from pkg import create_app
from pkg.models import db
from sqlalchemy import text

app = create_app()

with app.app_context():
    print("1. Creating any missing database tables...")
    db.create_all()

    print("2. Checking for missing columns...")
    engine = db.engine
    
    columns_to_check = [
        ("templates", "tenant_id", "INT NULL"),
        ("groups", "tenant_id", "INT NULL"),
        ("certificates", "tenant_id", "INT NULL"),
        ("users", "referral_code", "VARCHAR(10) NULL"),
        ("users", "referred_by", "INT NULL"),
        ("templates", "layout_data", "JSON NULL"),
        ("templates", "is_premium", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ]

    with engine.connect() as conn:
        for table, column, col_def in columns_to_check:
            try:
                check_sql = text(f"SHOW COLUMNS FROM `{table}` LIKE '{column}'")
                result = conn.execute(check_sql).fetchone()
                if not result:
                    print(f"Adding column `{column}` to table `{table}`...")
                    add_sql = text(f"ALTER TABLE `{table}` ADD COLUMN `{column}` {col_def}")
                    conn.execute(add_sql)
                    conn.commit()
                else:
                    print(f"Column `{column}` in `{table}` already exists.")
            except Exception as e:
                print(f"Note on `{table}.{column}`: {e}")

    print("Database sync complete!")
