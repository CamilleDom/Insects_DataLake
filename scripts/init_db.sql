-- Enable PostGIS extension
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================
-- STAGING ZONE
-- ============================================
CREATE SCHEMA IF NOT EXISTS staging;

-- Staging table for raw occurrences
CREATE TABLE IF NOT EXISTS staging.occurrences (
    id VARCHAR(255) PRIMARY KEY,
    species_name VARCHAR(255) NOT NULL,
    latitude FLOAT NOT NULL,
    longitude FLOAT NOT NULL,
    observed_on DATE,
    quality_grade VARCHAR(50),
    source VARCHAR(50) NOT NULL,  -- 'inaturalist' or 'gbif'
    raw_payload JSONB,
    ingested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_staging_occurrences_species ON staging.occurrences(species_name);
CREATE INDEX idx_staging_occurrences_source ON staging.occurrences(source);
CREATE INDEX idx_staging_occurrences_date ON staging.occurrences(observed_on);

-- ============================================
-- CURATED ZONE
-- ============================================
CREATE SCHEMA IF NOT EXISTS curated;

-- Table 1: Species richness by H3 cells
CREATE TABLE IF NOT EXISTS curated.species_richness_h3 (
    h3_cell VARCHAR(15) PRIMARY KEY,
    species_count INT NOT NULL,
    obs_count INT NOT NULL,
    richness_normalized FLOAT,
    richness_percentile FLOAT,
    lat_centroid FLOAT,
    lon_centroid FLOAT,
    last_observed DATE,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_richness_h3_percentile ON curated.species_richness_h3(richness_percentile DESC);
CREATE INDEX idx_richness_h3_updated ON curated.species_richness_h3(updated_at);

-- Table 2: Invasive species hotspots
CREATE TABLE IF NOT EXISTS curated.invasive_hotspots (
    id VARCHAR(255) PRIMARY KEY,
    h3_cell VARCHAR(15) NOT NULL,
    species_name VARCHAR(255) NOT NULL,
    invasive_risk VARCHAR(50),  -- 'high', 'medium', 'low'
    alert_count INT NOT NULL,
    first_seen DATE,
    last_seen DATE,
    lat_centroid FLOAT,
    lon_centroid FLOAT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(h3_cell, species_name)
);

CREATE INDEX idx_invasive_species ON curated.invasive_hotspots(species_name);
CREATE INDEX idx_invasive_risk ON curated.invasive_hotspots(invasive_risk);
CREATE INDEX idx_invasive_updated ON curated.invasive_hotspots(updated_at);

-- ============================================
-- AUDIT & METRICS
-- ============================================
CREATE SCHEMA IF NOT EXISTS audit;

CREATE TABLE IF NOT EXISTS audit.ingestion_log (
    id VARCHAR(255) PRIMARY KEY,
    source VARCHAR(50),
    status VARCHAR(50),  -- 'success', 'failed'
    record_count INT,
    error_message TEXT,
    started_at TIMESTAMP,
    completed_at TIMESTAMP
);

CREATE INDEX idx_audit_source ON audit.ingestion_log(source);
CREATE INDEX idx_audit_completed ON audit.ingestion_log(completed_at);

-- ============================================
-- INVASIVE SPECIES REFERENCE LIST
-- ============================================
CREATE TABLE IF NOT EXISTS public.invasive_species_list (
    id SERIAL PRIMARY KEY,
    species_name VARCHAR(255) UNIQUE NOT NULL,
    risk_level VARCHAR(50),  -- 'high', 'medium', 'low'
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Insert invasive species reference data
INSERT INTO public.invasive_species_list (species_name, risk_level, description) VALUES
    ('Vespa velutina', 'high', 'Asian hornet - threatens honeybees and native insects'),
    ('Harmonia axyridis', 'high', 'Asian ladybird - preys on native insects'),
    ('Sciurus carolinensis', 'medium', 'Eastern gray squirrel - competes with native species'),
    ('Procyon lotor', 'medium', 'Raccoon - predator of birds and amphibians')
ON CONFLICT (species_name) DO NOTHING;
