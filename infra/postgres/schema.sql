CREATE TABLE IF NOT EXISTS groups (
    id BIGSERIAL PRIMARY KEY,
    group_code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS stores (
    id BIGSERIAL PRIMARY KEY,
    group_db_id BIGINT NOT NULL REFERENCES groups(id) ON DELETE RESTRICT,
    store_id TEXT NOT NULL,
    name TEXT NOT NULL,
    street TEXT NOT NULL DEFAULT '',
    number TEXT NOT NULL DEFAULT '',
    neighborhood TEXT NOT NULL DEFAULT '',
    city TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL DEFAULT '',
    cep TEXT NOT NULL DEFAULT '',
    timezone TEXT NOT NULL DEFAULT 'America/Sao_Paulo',
    ocr_sample_interval_sec INTEGER NOT NULL DEFAULT 30,
    ocr_min_confidence DOUBLE PRECISION NOT NULL DEFAULT 0.5,
    pos_match_delta_sec INTEGER NOT NULL DEFAULT 20,
    r1_min_checkout_duration_sec DOUBLE PRECISION NOT NULL DEFAULT 20,
    t_return_sec DOUBLE PRECISION NOT NULL DEFAULT 1800,
    r3_visual_margin INTEGER NOT NULL DEFAULT 2,
    carry_confidence_threshold DOUBLE PRECISION NOT NULL DEFAULT 0.55,
    r4_min_items INTEGER NOT NULL DEFAULT 5,
    r4_fast_duration_sec DOUBLE PRECISION NOT NULL DEFAULT 90,
    enable_r4 BOOLEAN NOT NULL DEFAULT TRUE,
    r5_cancelled_delta_sec INTEGER NOT NULL DEFAULT 60,
    buffer_before_sec DOUBLE PRECISION NOT NULL DEFAULT 20,
    buffer_after_sec DOUBLE PRECISION NOT NULL DEFAULT 20,
    checkout_buffer_before_sec DOUBLE PRECISION NOT NULL DEFAULT 5,
    checkout_buffer_after_sec DOUBLE PRECISION NOT NULL DEFAULT 5,
    vid_stride INTEGER NOT NULL DEFAULT 5,
    evidence_scale_width INTEGER,
    evidence_ffmpeg_preset TEXT NOT NULL DEFAULT 'fast',
    evidence_crf INTEGER NOT NULL DEFAULT 28,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (group_db_id, store_id)
);

CREATE TABLE IF NOT EXISTS cameras (
    id BIGSERIAL PRIMARY KEY,
    store_db_id BIGINT NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    camera_id TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    camera_role TEXT NOT NULL DEFAULT 'support',
    ocr_x INTEGER NOT NULL DEFAULT 10,
    ocr_y INTEGER NOT NULL DEFAULT 10,
    ocr_width INTEGER NOT NULL DEFAULT 420,
    ocr_height INTEGER NOT NULL DEFAULT 50,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (store_db_id, camera_id)
);

CREATE TABLE IF NOT EXISTS users (
    id BIGSERIAL PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS camera_zones (
    id BIGSERIAL PRIMARY KEY,
    camera_db_id BIGINT NOT NULL REFERENCES cameras(id) ON DELETE CASCADE,
    zone_type TEXT NOT NULL,
    zone_id TEXT NOT NULL,
    label TEXT NOT NULL DEFAULT '',
    lane_id INTEGER,
    polygon_json TEXT NOT NULL,
    entry_vector_json TEXT,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (camera_db_id, zone_id)
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    id BIGSERIAL PRIMARY KEY,
    store_db_id BIGINT NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    date TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    current_phase TEXT NOT NULL DEFAULT '',
    current_camera TEXT,
    worker_node TEXT,
    worker_id TEXT,
    job_id TEXT,
    log_path TEXT,
    error_message TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS alert_reviews (
    id BIGSERIAL PRIMARY KEY,
    store_db_id BIGINT NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    date TEXT NOT NULL,
    alert_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending_review',
    reviewer_user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
    note TEXT NOT NULL DEFAULT '',
    reviewed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (store_db_id, date, alert_id)
);

CREATE INDEX IF NOT EXISTS idx_stores_group ON stores(group_db_id);
CREATE INDEX IF NOT EXISTS idx_cameras_store ON cameras(store_db_id);
CREATE INDEX IF NOT EXISTS idx_camera_zones_camera ON camera_zones(camera_db_id);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_store ON pipeline_runs(store_db_id);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_status ON pipeline_runs(status);
CREATE INDEX IF NOT EXISTS idx_alert_reviews_store_date ON alert_reviews(store_db_id, date);
