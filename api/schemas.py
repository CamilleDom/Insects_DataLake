from pydantic import BaseModel
from typing import List, Optional
from datetime import date

# ============================================
# HEALTH & DIAGNOSTICS
# ============================================

class HealthResponse(BaseModel):
    status: str  # 'healthy' or 'degraded'
    timestamp: str
    services: dict

# ============================================
# STATS
# ============================================

class StatsResponse(BaseModel):
    timestamp: str
    staging_occurrences: int
    curated_h3_cells: int
    invasive_hotspots: int
    last_ingestion: Optional[str] = None

# ============================================
# OBSERVATIONS
# ============================================

class Observation(BaseModel):
    species_name: str
    latitude: float
    longitude: float
    observed_on: date

class ObservationsPayload(BaseModel):
    observations: List[Observation]

class IngestPayload(BaseModel):
    data: ObservationsPayload

# ============================================
# RESPONSES
# ============================================

class BiodiversityHotspot(BaseModel):
    h3_cell: str
    species_count: int
    observation_count: int
    richness_normalized: float
    richness_percentile: float
    latitude: float
    longitude: float
    last_observed: Optional[str] = None

class InvasiveAlert(BaseModel):
    h3_cell: str
    species_name: str
    invasive_risk: str
    alert_count: int
    first_seen: Optional[str] = None
    last_seen: Optional[str] = None
    latitude: float
    longitude: float
