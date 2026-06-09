-- DataPond Data Connectors Schema
-- PostgreSQL database schema for connector metadata

-- Connector connections table
CREATE TABLE IF NOT EXISTS connector_connections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    connector_type VARCHAR(50) NOT NULL,
    config_encrypted TEXT NOT NULL,
    description TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    last_sync_at TIMESTAMP,
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    CONSTRAINT check_status CHECK (status IN ('active', 'paused', 'error', 'testing'))
);

-- Create index on status for faster filtering
CREATE INDEX idx_connector_connections_status ON connector_connections(status);
CREATE INDEX idx_connector_connections_type ON connector_connections(connector_type);

-- Sync jobs table
CREATE TABLE IF NOT EXISTS connector_sync_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    connection_id UUID NOT NULL REFERENCES connector_connections(id) ON DELETE CASCADE,
    source_table VARCHAR(255) NOT NULL,
    target_table VARCHAR(255) NOT NULL,
    sync_mode VARCHAR(20) NOT NULL DEFAULT 'full',
    schedule VARCHAR(50),
    incremental_column VARCHAR(100),
    last_value TEXT,
    partition_spec JSONB,          -- [{"column":"created_at","transform":"day"}] · NULL이면 자동 추론
    key_columns JSONB,             -- ["id"] 증분 upsert(merge) PK · NULL/[]이면 append(upsert 비활성)
    primary_keys TEXT[],           -- (legacy, 미사용 — key_columns 사용)
    last_run_at TIMESTAMP,
    last_run_status VARCHAR(20),
    rows_synced INTEGER DEFAULT 0,
    enabled BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT check_sync_mode CHECK (sync_mode IN ('full', 'incremental', 'cdc', 'snapshot')),
    CONSTRAINT check_last_run_status CHECK (last_run_status IS NULL OR last_run_status IN ('success', 'failed', 'running', 'pending', 'cancelled'))
);

-- Create indexes for job queries
CREATE INDEX idx_connector_sync_jobs_connection ON connector_sync_jobs(connection_id);
CREATE INDEX idx_connector_sync_jobs_status ON connector_sync_jobs(last_run_status);
CREATE INDEX idx_connector_sync_jobs_last_run ON connector_sync_jobs(last_run_at DESC);

-- Sync history table (detailed execution logs)
CREATE TABLE IF NOT EXISTS connector_sync_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id UUID NOT NULL REFERENCES connector_sync_jobs(id) ON DELETE CASCADE,
    started_at TIMESTAMP NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMP,
    status VARCHAR(20) NOT NULL,
    rows_processed INTEGER DEFAULT 0,
    rows_failed INTEGER DEFAULT 0,
    error_message TEXT,
    metadata JSONB,
    CONSTRAINT check_history_status CHECK (status IN ('success', 'failed', 'running', 'pending', 'cancelled'))
);

-- Create indexes for history queries
CREATE INDEX idx_connector_sync_history_job ON connector_sync_history(job_id);
CREATE INDEX idx_connector_sync_history_started ON connector_sync_history(started_at DESC);
CREATE INDEX idx_connector_sync_history_status ON connector_sync_history(status);

-- Connector credentials audit log (optional - for compliance)
CREATE TABLE IF NOT EXISTS connector_credentials_audit (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    connection_id UUID NOT NULL REFERENCES connector_connections(id) ON DELETE CASCADE,
    action VARCHAR(50) NOT NULL,
    performed_by VARCHAR(255),
    performed_at TIMESTAMP NOT NULL DEFAULT NOW(),
    details JSONB,
    CONSTRAINT check_action CHECK (action IN ('created', 'updated', 'deleted', 'accessed', 'rotated'))
);

CREATE INDEX idx_connector_credentials_audit_connection ON connector_credentials_audit(connection_id);
CREATE INDEX idx_connector_credentials_audit_performed ON connector_credentials_audit(performed_at DESC);

-- Function to automatically update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Triggers for updated_at
CREATE TRIGGER update_connector_connections_updated_at
    BEFORE UPDATE ON connector_connections
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_connector_sync_jobs_updated_at
    BEFORE UPDATE ON connector_sync_jobs
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- View for connection health summary
CREATE OR REPLACE VIEW connector_health_summary AS
SELECT
    cc.id,
    cc.name,
    cc.connector_type,
    cc.status,
    cc.last_sync_at,
    COUNT(csj.id) AS total_jobs,
    SUM(CASE WHEN csj.last_run_status = 'success' THEN 1 ELSE 0 END) AS successful_jobs,
    SUM(CASE WHEN csj.last_run_status = 'failed' THEN 1 ELSE 0 END) AS failed_jobs,
    SUM(CASE WHEN csj.last_run_status = 'running' THEN 1 ELSE 0 END) AS running_jobs,
    SUM(csj.rows_synced) AS total_rows_synced
FROM
    connector_connections cc
    LEFT JOIN connector_sync_jobs csj ON cc.id = csj.connection_id
GROUP BY
    cc.id, cc.name, cc.connector_type, cc.status, cc.last_sync_at;

-- Sample data for testing (optional)
-- INSERT INTO connector_connections (name, connector_type, config_encrypted, status)
-- VALUES
--     ('Production PostgreSQL', 'postgresql', 'encrypted_data_here', 'active'),
--     ('Analytics MySQL', 'mysql', 'encrypted_data_here', 'active'),
--     ('Data Lake S3', 's3', 'encrypted_data_here', 'active');
