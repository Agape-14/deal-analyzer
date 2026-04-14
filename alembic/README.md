# Migrations (Alembic)

This repo manages schema with Alembic. The Railway start command runs
`alembic upgrade head` before booting uvicorn — no manual step needed
on deploy.

## Day-to-day

### Add / modify a column
1. Change `app/models.py`
2. From the repo root:
   ```bash
   alembic revision --autogenerate -m "describe the change"
   ```
3. Review the generated file in `alembic/versions/` — autogenerate is
   conservative but not perfect; confirm the SQL matches intent.
4. Apply locally:
   ```bash
   alembic upgrade head
   ```
5. Commit the migration file along with the model change. On the next
   deploy, Railway's startup hook will run `upgrade head`.

### Roll back one step
```bash
alembic downgrade -1
```

### Show current state
```bash
alembic current
alembic history
```

### Stamp an existing DB (for databases that predate Alembic)
If you have a production DB that was populated by the old
`init_db -> create_all` path, mark it as already at the head revision
without running any migrations:
```bash
alembic stamp head
```

## Notes

- `env.py` uses our async engine and pulls the URL from
  `app.database.DATABASE_URL`, which honors `DATABASE_URL` / `DB_DIR`
  env vars. Don't edit the URL in `alembic.ini`.
- SQLite migrations use Alembic batch mode (`render_as_batch=True`) so
  ALTER TABLE diffs work cleanly. Postgres ignores batch mode.
- `app/database.py::init_db` detects the `alembic_version` table and
  short-circuits — it won't fight Alembic. The legacy ALTER-if-missing
  path stays in place for developers running a raw SQLite without
  invoking Alembic.
