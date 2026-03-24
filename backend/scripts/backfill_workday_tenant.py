"""One-time backfill: set workday_tenant on existing applications from source_url.

Usage:
    DATABASE_URL_DIRECT=... python -m scripts.backfill_workday_tenant

Uses DATABASE_URL_DIRECT (port 5432) — never the pooled connection.
"""

import os

from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session

from app.models.application import Application
from app.utils.workday import extract_workday_tenant


def main() -> None:
    url = os.environ["DATABASE_URL_DIRECT"]
    engine = create_engine(url)

    with Session(engine) as db:
        rows = db.execute(
            select(Application.id, Application.source_url).where(
                Application.source_url.isnot(None),
                Application.workday_tenant.is_(None),
            )
        ).all()

        updated = 0
        for i, (app_id, source_url) in enumerate(rows, 1):
            tenant = extract_workday_tenant(source_url)
            if tenant:
                db.execute(
                    update(Application)
                    .where(Application.id == app_id)
                    .values(workday_tenant=tenant)
                )
                updated += 1
            if i % 100 == 0:
                db.commit()

        db.commit()
        print(f"Backfill complete: updated {updated} of {len(rows)} applications")


if __name__ == "__main__":
    main()
