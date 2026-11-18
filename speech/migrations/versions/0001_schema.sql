CREATE TABLE benchmark_runs (
	id VARCHAR(100) NOT NULL, 
	status VARCHAR(30) NOT NULL, 
	manifest JSONB NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
);

CREATE TABLE model_versions (
	id VARCHAR(100) NOT NULL, 
	manifest JSONB NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
);

CREATE TABLE sessions (
	id VARCHAR(36) NOT NULL, 
	owner VARCHAR(100) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	metadata_json JSONB NOT NULL, 
	revision INTEGER NOT NULL, 
	deleted BOOLEAN NOT NULL, 
	result JSONB, 
	PRIMARY KEY (id)
);

CREATE INDEX ix_sessions_deleted ON sessions (deleted);

CREATE TABLE audio_assets (
	id VARCHAR(36) NOT NULL, 
	session_id VARCHAR(36) NOT NULL, 
	locator VARCHAR(300) NOT NULL, 
	sha256 VARCHAR(64) NOT NULL, 
	size_bytes INTEGER NOT NULL, 
	diagnostics JSONB, 
	PRIMARY KEY (id), 
	UNIQUE (session_id), 
	FOREIGN KEY(session_id) REFERENCES sessions (id)
);

CREATE INDEX ix_audio_assets_sha256 ON audio_assets (sha256);

CREATE TABLE events (
	id VARCHAR(36) NOT NULL, 
	session_id VARCHAR(36) NOT NULL, 
	event_id VARCHAR(100) NOT NULL, 
	start_sec FLOAT NOT NULL, 
	end_sec FLOAT NOT NULL, 
	payload JSONB NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (session_id, event_id), 
	FOREIGN KEY(session_id) REFERENCES sessions (id)
);

CREATE INDEX ix_events_session_id ON events (session_id);

CREATE TABLE processing_jobs (
	id VARCHAR(36) NOT NULL, 
	session_id VARCHAR(36), 
	owner VARCHAR(100) NOT NULL, 
	kind VARCHAR(20) NOT NULL, 
	idempotency_key VARCHAR(200) NOT NULL, 
	request_hash VARCHAR(64) NOT NULL, 
	request_json JSONB NOT NULL, 
	config_json JSONB NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	stage VARCHAR(50) NOT NULL, 
	progress FLOAT NOT NULL, 
	attempts INTEGER NOT NULL, 
	cancel_requested BOOLEAN NOT NULL, 
	attempt_token VARCHAR(36), 
	lease_until TIMESTAMP WITH TIME ZONE, 
	error JSONB, 
	result JSONB, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (owner, idempotency_key), 
	FOREIGN KEY(session_id) REFERENCES sessions (id)
);

CREATE INDEX ix_processing_jobs_session_id ON processing_jobs (session_id);

CREATE INDEX ix_processing_jobs_status ON processing_jobs (status);

CREATE TABLE review_revisions (
	id VARCHAR(36) NOT NULL, 
	session_id VARCHAR(36) NOT NULL, 
	revision INTEGER NOT NULL, 
	author VARCHAR(100) NOT NULL, 
	reason VARCHAR NOT NULL, 
	before JSONB NOT NULL, 
	after JSONB NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (session_id, revision), 
	FOREIGN KEY(session_id) REFERENCES sessions (id)
);

CREATE INDEX ix_review_revisions_session_id ON review_revisions (session_id);

CREATE TABLE transcript_segments (
	id VARCHAR(36) NOT NULL, 
	session_id VARCHAR(36) NOT NULL, 
	segment_id VARCHAR(100) NOT NULL, 
	start_sec FLOAT NOT NULL, 
	end_sec FLOAT NOT NULL, 
	payload JSONB NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (session_id, segment_id), 
	FOREIGN KEY(session_id) REFERENCES sessions (id)
);

CREATE INDEX ix_transcript_segments_session_id ON transcript_segments (session_id);

CREATE TABLE job_attempts (
	token VARCHAR(36) NOT NULL, 
	job_id VARCHAR(36) NOT NULL, 
	number INTEGER NOT NULL, 
	started_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	finished_at TIMESTAMP WITH TIME ZONE, 
	status VARCHAR(30) NOT NULL, 
	error JSONB, 
	PRIMARY KEY (token), 
	FOREIGN KEY(job_id) REFERENCES processing_jobs (id)
);

CREATE INDEX ix_job_attempts_job_id ON job_attempts (job_id);

CREATE TABLE outbox_events (
	id VARCHAR(36) NOT NULL, 
	job_id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	published_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(job_id) REFERENCES processing_jobs (id)
);

CREATE INDEX ix_outbox_events_job_id ON outbox_events (job_id);

CREATE INDEX ix_outbox_events_published_at ON outbox_events (published_at);

CREATE TABLE pipeline_runs (
	id VARCHAR(36) NOT NULL, 
	job_id VARCHAR(36) NOT NULL, 
	attempt_token VARCHAR(36) NOT NULL, 
	config_hash VARCHAR(64) NOT NULL, 
	manifest JSONB NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (job_id), 
	FOREIGN KEY(job_id) REFERENCES processing_jobs (id)
);
