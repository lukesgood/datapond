-- DataPond Query History & Dashboard Schema
-- PostgreSQL database schema for SQL Lab features

-- ============================================================================
-- QUERY HISTORY
-- ============================================================================

CREATE TABLE IF NOT EXISTS query_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    query_text TEXT NOT NULL,
    execution_time_ms INTEGER NOT NULL,
    rows_returned INTEGER NOT NULL DEFAULT 0,
    status VARCHAR(20) NOT NULL DEFAULT 'success',
    error_message TEXT,
    catalog VARCHAR(128),
    schema VARCHAR(128),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT check_status CHECK (status IN ('success', 'error', 'timeout', 'cancelled'))
);

-- Indexes for fast query history lookups
CREATE INDEX idx_query_history_user ON query_history(user_id, created_at DESC);
CREATE INDEX idx_query_history_status ON query_history(status);
CREATE INDEX idx_query_history_created ON query_history(created_at DESC);

-- ============================================================================
-- DASHBOARDS
-- ============================================================================

CREATE TABLE IF NOT EXISTS dashboards (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    query_text TEXT NOT NULL,
    chart_config JSONB NOT NULL DEFAULT '{}',
    is_public BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT check_name_not_empty CHECK (TRIM(name) <> '')
);

-- Indexes for fast dashboard lookups
CREATE INDEX idx_dashboards_user ON dashboards(user_id, created_at DESC);
CREATE INDEX idx_dashboards_public ON dashboards(is_public, created_at DESC);
CREATE INDEX idx_dashboards_updated ON dashboards(updated_at DESC);

-- Trigger to auto-update updated_at
CREATE OR REPLACE FUNCTION update_dashboard_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_dashboards_updated_at
    BEFORE UPDATE ON dashboards
    FOR EACH ROW
    EXECUTE FUNCTION update_dashboard_updated_at();

-- ============================================================================
-- DASHBOARD SHARING (OPTIONAL - FOR FUTURE)
-- ============================================================================

CREATE TABLE IF NOT EXISTS dashboard_shares (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    dashboard_id UUID NOT NULL REFERENCES dashboards(id) ON DELETE CASCADE,
    shared_with_user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    shared_with_role_id UUID REFERENCES roles(id) ON DELETE CASCADE,
    permission VARCHAR(20) NOT NULL DEFAULT 'view',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    CONSTRAINT check_share_target CHECK (
        (shared_with_user_id IS NOT NULL AND shared_with_role_id IS NULL) OR
        (shared_with_user_id IS NULL AND shared_with_role_id IS NOT NULL)
    ),
    CONSTRAINT check_permission CHECK (permission IN ('view', 'edit')),
    CONSTRAINT uq_dashboard_share UNIQUE (dashboard_id, shared_with_user_id, shared_with_role_id)
);

CREATE INDEX idx_dashboard_shares_dashboard ON dashboard_shares(dashboard_id);
CREATE INDEX idx_dashboard_shares_user ON dashboard_shares(shared_with_user_id);
CREATE INDEX idx_dashboard_shares_role ON dashboard_shares(shared_with_role_id);

-- ============================================================================
-- QUERY FAVORITES (OPTIONAL - FOR FUTURE)
-- ============================================================================

CREATE TABLE IF NOT EXISTS query_favorites (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    query_text TEXT NOT NULL,
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_query_favorite_name UNIQUE (user_id, name)
);

CREATE INDEX idx_query_favorites_user ON query_favorites(user_id, created_at DESC);
