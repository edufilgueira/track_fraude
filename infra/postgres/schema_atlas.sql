CREATE SCHEMA IF NOT EXISTS atlas;

CREATE TABLE IF NOT EXISTS atlas.gpu_pools (
    id BIGSERIAL PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS atlas.workloads (
    id BIGSERIAL PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    image TEXT NOT NULL,
    queue_name TEXT NOT NULL,
    k8s_namespace TEXT NOT NULL DEFAULT 'track-fraude',
    gpu_pool_id BIGINT REFERENCES atlas.gpu_pools(id) ON DELETE SET NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    config_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS atlas.api_keys (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    key_prefix TEXT NOT NULL,
    key_hash TEXT NOT NULL UNIQUE,
    scopes JSONB NOT NULL DEFAULT '[]'::jsonb,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS atlas.jobs (
    id BIGSERIAL PRIMARY KEY,
    public_id TEXT NOT NULL UNIQUE,
    workload_id BIGINT NOT NULL REFERENCES atlas.workloads(id) ON DELETE RESTRICT,
    status TEXT NOT NULL DEFAULT 'queued',
    payload JSONB NOT NULL,
    pipeline_run_id BIGINT,
    rabbit_message_id TEXT,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_atlas_jobs_workload ON atlas.jobs(workload_id);
CREATE INDEX IF NOT EXISTS idx_atlas_jobs_status ON atlas.jobs(status);
CREATE INDEX IF NOT EXISTS idx_atlas_jobs_pipeline_run ON atlas.jobs(pipeline_run_id);

INSERT INTO atlas.gpu_pools (slug, name)
VALUES ('video', 'Vídeo / pipeline')
ON CONFLICT (slug) DO NOTHING;

INSERT INTO atlas.workloads (
    slug, name, image, queue_name, k8s_namespace, gpu_pool_id, config_json
)
SELECT
    'track-fraude',
    'Track Fraude Pipeline',
    '192.168.0.199:5000/track-fraude-worker:latest',
    'track-fraude-pipelines',
    'track-fraude',
    (SELECT id FROM atlas.gpu_pools WHERE slug = 'video'),
    '{"command":["python","jobs/run_pipeline_queue_worker.py"],"gpu_pool":"video"}'::jsonb
WHERE NOT EXISTS (SELECT 1 FROM atlas.workloads WHERE slug = 'track-fraude');

INSERT INTO atlas.api_keys (name, key_prefix, key_hash, scopes)
SELECT
    'internal-ui',
    'atlas-dev',
    'f50f6d80fc9c1dcfa54cf266d21cca3f3051f784a260681b00673b7def088034',
    '["*"]'::jsonb
WHERE NOT EXISTS (
    SELECT 1 FROM atlas.api_keys WHERE name = 'internal-ui'
);
