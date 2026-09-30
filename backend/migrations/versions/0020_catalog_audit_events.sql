-- Adding, changing and removing a data catalog (app/api/catalog_admin.py) writes an
-- auth audit row. audit_event_type is an enum and the audit insert is best-effort, so
-- without these values every catalog change would leave no trace — silently.
--
-- ADD VALUE is additive: the previous release never writes them and reads rows by
-- column, so it runs against either release.
ALTER TYPE public.audit_event_type ADD VALUE IF NOT EXISTS 'catalog_created';
ALTER TYPE public.audit_event_type ADD VALUE IF NOT EXISTS 'catalog_updated';
ALTER TYPE public.audit_event_type ADD VALUE IF NOT EXISTS 'catalog_deleted';
