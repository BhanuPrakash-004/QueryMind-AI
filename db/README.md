# Database setup

## Supabase (production)

1. Create or open a Supabase project.
2. Open **Dashboard → Connect** and copy the connection strings. Use the
   **Session Pooler** when your network is IPv4-only; use the direct connection
   only when your network supports it.
3. In the Supabase SQL editor, run `db/schema.sql` with an administrative
   connection.
4. Edit `db/runtime_role.sql`:
   - replace `CHANGE_ME_WITH_A_LONG_RANDOM_PASSWORD` with a strong password;
   - run the file in the SQL editor.
5. Put the administrative URL in `DATABASE_ADMIN_URL` and the
   `sales_runtime` URL in `DATABASE_URL` in `.env`:

```dotenv
DATABASE_ADMIN_URL=postgresql://postgres.<project-ref>:<password>@<host>:5432/postgres
DATABASE_URL=postgresql://sales_runtime.<project-ref>:<password>@<host>:5432/postgres
```

When connecting through the Session Pooler, a custom role's username must be
`<role>.<project-ref>` (for example `sales_runtime.ufblkllpqwbkqukkysrc`), not
just `sales_runtime`. URL-encode any `@` in a password as `%40`.

Both `postgresql://` and `postgres://` URLs are normalized to
`postgresql+psycopg://` by the backend. Non-local hosts get `sslmode=require`
unless the URL already specifies an SSL mode.

The runtime role is read-only, is not the table owner, and has no schema
creation rights. The backend never falls back to `DATABASE_ADMIN_URL` for
runtime queries.

## Local verification (optional)

The repository was verified against a local PostgreSQL 17 Docker container:

```powershell
docker run -d --name sales-intelligence-db `
  -e POSTGRES_USER=postgres `
  -e POSTGRES_PASSWORD=postgres `
  -e POSTGRES_DB=sales_intelligence `
  -p 5433:5432 postgres:17-alpine
```

Apply the schema and role, then set a local runtime password:

```powershell
docker cp db/schema.sql sales-intelligence-db:/tmp/schema.sql
docker exec sales-intelligence-db psql -U postgres -d sales_intelligence `
  -v ON_ERROR_STOP=1 -f /tmp/schema.sql

docker cp db/runtime_role.sql sales-intelligence-db:/tmp/runtime_role.sql
docker exec sales-intelligence-db psql -U postgres -d sales_intelligence `
  -v ON_ERROR_STOP=1 -f /tmp/runtime_role.sql

docker exec sales-intelligence-db psql -U postgres -d sales_intelligence `
  -c "ALTER ROLE sales_runtime PASSWORD 'sales_runtime_dev_password';"
```

Local `.env` values:

```dotenv
DATABASE_ADMIN_URL=postgresql+psycopg://postgres:postgres@localhost:5433/sales_intelligence
DATABASE_URL=postgresql+psycopg://sales_runtime:sales_runtime_dev_password@localhost:5433/sales_intelligence
```

## Verify the runtime role is read-only

```powershell
cd backend
.venv\Scripts\python.exe -c "from sqlalchemy import text; from app.database import get_runtime_engine; e=get_runtime_engine(); print('rows', e.connect().execute(text('select count(*) from sales_transactions')).scalar()); c=e.connect(); t=c.begin(); c.execute(text('insert into sales_transactions values (\'X\', current_date, \'p\', \'c\', \'r\', \'Online\', 1, 1, 0, \'completed\')'))"
```

The final `INSERT` must fail with a read-only/transaction error. The admin
connection is only for `db/schema.sql`, migrations, and `app.import_csv`.
