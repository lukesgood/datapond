-- RisingWave and the Streaming module were removed in 2.7. Their four rows in the
-- legacy permissions table ('streaming' create_mv / create_source / drop / query) name
-- a module that no longer exists. role_permissions rows go with them (ON DELETE CASCADE).
-- Nothing reads these rows: route checks use app/permissions.py.
DELETE FROM public.permissions WHERE resource = 'streaming';
