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
    from sqlalchemy import inspect
    engine = db.engine
    dialect = engine.dialect.name
    
    columns_to_check = [
        ("templates", "tenant_id", "INT NULL" if dialect != "postgresql" else "INTEGER NULL"),
        ("groups", "tenant_id", "INT NULL" if dialect != "postgresql" else "INTEGER NULL"),
        ("certificates", "tenant_id", "INT NULL" if dialect != "postgresql" else "INTEGER NULL"),
        ("users", "referral_code", "VARCHAR(10) NULL"),
        ("users", "referred_by", "INT NULL" if dialect != "postgresql" else "INTEGER NULL"),
        ("templates", "layout_data", "JSON NULL"),
        ("templates", "is_premium", "BOOLEAN NOT NULL DEFAULT FALSE"),
        ("tenants", "linkedin_org_id", "VARCHAR(50) NULL"),
        ("referrals", "credits_earned", "INT NOT NULL DEFAULT 0" if dialect != "postgresql" else "INTEGER NOT NULL DEFAULT 0"),
        # BackgroundJob columns
        ("background_jobs", "celery_task_id", "VARCHAR(255) NULL"),
        ("background_jobs", "result_summary", "JSON NULL"),
        # Notification columns
        ("notifications", "reference_id", "INT NULL" if dialect != "postgresql" else "INTEGER NULL"),
    ]

    try:
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        with engine.connect() as conn:
            for table, column, col_def in columns_to_check:
                if table not in tables:
                    continue
                col_names = [c['name'] for c in inspector.get_columns(table)]
                if column not in col_names:
                    print(f"Adding column `{column}` to table `{table}`...")
                    add_sql = text(f'ALTER TABLE "{table}" ADD COLUMN "{column}" {col_def}' if dialect == "postgresql" else f"ALTER TABLE `{table}` ADD COLUMN `{column}` {col_def}")
                    conn.execute(add_sql)
                    conn.commit()
                else:
                    print(f"Column `{column}` in `{table}` already exists.")
    except Exception as e:
        print(f"Schema column check notice: {e}")

    print("Database sync complete!")
