-- Run this against Docker Postgres when alembic_version has a revision that no longer exists
-- (e.g. 0004_add_audit_questions) and you need product/cart/checkout in page_type_enum.
--
-- Usage (use your POSTGRES_USER from .env, e.g. rinor):
--   docker-compose exec -T postgres psql -U rinor -d ai_website_audit < migrations/versions/fix_docker_enum_and_version.sql
-- Or paste into psql:
--   docker-compose exec postgres psql -U rinor -d ai_website_audit

DO $$ BEGIN ALTER TYPE page_type_enum ADD VALUE IF NOT EXISTS 'product'; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN ALTER TYPE page_type_enum ADD VALUE IF NOT EXISTS 'cart'; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN ALTER TYPE page_type_enum ADD VALUE IF NOT EXISTS 'checkout'; EXCEPTION WHEN duplicate_object THEN NULL; END $$;

UPDATE alembic_version SET version_num = '0004_add_ecom_page_types' WHERE version_num LIKE '0004%';
