#!/usr/bin/env python3
"""Update all route files to use get_bound_db instead of get_db."""
import re
from pathlib import Path

ROUTES_DIR = Path("/home/eamon/Fantasy-Football-Isle-of-Man/app/routes")

# Route files to update (those that need cross-database access)
ROUTE_FILES = list(ROUTES_DIR.glob("*.py"))

updated = []

for filepath in ROUTE_FILES:
    content = filepath.read_text()
    original = content

    # Update import: add get_bound_db to imports from app.database
    # Pattern: from app.database import get_db
    content = re.sub(
        r'from app\.database import get_db',
        'from app.database import get_db, get_bound_db',
        content
    )

    # Replace Depends(get_db) with Depends(get_bound_db)
    content = content.replace('Depends(get_db)', 'Depends(get_bound_db)')

    if content != original:
        filepath.write_text(content)
        updated.append(filepath.name)

print(f"Updated {len(updated)} route files:")
for f in updated:
    print(f"  {f}")
