# breadth_v2 migrations

These migrations own only the PostgreSQL `breadth_v2` schema. They never create,
alter, or drop legacy objects in `public`, including `public.breadth_snapshots`.

Set `BREADTH_V2_DATABASE_URL` and run `alembic upgrade head`. Application writer
and reader credentials must not own the schema or run migrations.
