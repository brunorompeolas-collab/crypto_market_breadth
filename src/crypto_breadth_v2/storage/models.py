"""SQLAlchemy models for the approved ``breadth_v2`` PostgreSQL schema."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    Numeric,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


SCHEMA = "breadth_v2"
PRICE = Numeric(38, 18)
PERCENT = Numeric(9, 6)

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(schema=SCHEMA, naming_convention=NAMING_CONVENTION)


class Asset(Base):
    __tablename__ = "assets"
    __table_args__ = (
        CheckConstraint("status IN ('ACTIVE','INACTIVE')", name="status"),
    )

    asset_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    canonical_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    metadata_id: Mapped[Optional[str]] = mapped_column(String(100))
    legacy_identity: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DataSource(Base):
    __tablename__ = "data_sources"
    __table_args__ = (
        CheckConstraint("market_type IN ('SPOT')", name="market_type"),
        CheckConstraint("terms_review_status IN ('PENDING','ACCEPTED','REJECTED')", name="terms_review_status"),
    )

    source_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    venue: Mapped[str] = mapped_column(String(100), nullable=False)
    market_type: Mapped[str] = mapped_column(String(16), nullable=False)
    api_base_url: Mapped[str] = mapped_column(Text, nullable=False)
    terms_url: Mapped[str] = mapped_column(Text, nullable=False)
    terms_review_status: Mapped[str] = mapped_column(String(16), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class SourceVersion(Base):
    __tablename__ = "source_versions"
    __table_args__ = (
        UniqueConstraint("source_id", "adapter_version", "api_schema_hash", "archive_release"),
        UniqueConstraint(
            "source_version_id", "source_id", name="uq_source_version_source"
        ),
    )

    source_version_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    source_id: Mapped[str] = mapped_column(ForeignKey(f"{SCHEMA}.data_sources.source_id"), nullable=False)
    adapter_version: Mapped[str] = mapped_column(String(64), nullable=False)
    api_contract_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    api_schema_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    archive_release: Mapped[str] = mapped_column(String(100), nullable=False, default="NONE")
    archive_checksum: Mapped[Optional[str]] = mapped_column(String(64))
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProviderMapping(Base):
    __tablename__ = "provider_mappings"
    __table_args__ = (
        UniqueConstraint("source_id", "instrument_id", "mapping_version"),
        UniqueConstraint("mapping_id", "asset_id", name="uq_provider_mapping_asset"),
        UniqueConstraint(
            "mapping_id", "asset_id", "source_id", name="uq_provider_mapping_asset_source"
        ),
        CheckConstraint("status IN ('ACTIVE','DELISTED','DISABLED')", name="status"),
        CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="valid_range"),
    )

    mapping_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    asset_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.assets.asset_id"), nullable=False)
    source_id: Mapped[str] = mapped_column(ForeignKey(f"{SCHEMA}.data_sources.source_id"), nullable=False)
    provider_asset_id: Mapped[str] = mapped_column(String(100), nullable=False)
    base_code: Mapped[str] = mapped_column(String(32), nullable=False)
    quote_code: Mapped[str] = mapped_column(String(32), nullable=False)
    instrument_id: Mapped[str] = mapped_column(String(100), nullable=False)
    mapping_version: Mapped[str] = mapped_column(String(64), nullable=False)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_to: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), nullable=False)


class UniverseVersion(Base):
    __tablename__ = "universe_versions"
    __table_args__ = (
        CheckConstraint("series_kind IN ('LIVE','RESEARCH')", name="series_kind"),
        CheckConstraint("status IN ('DRAFT','ACTIVE','RETIRED')", name="status"),
        CheckConstraint("expected_size > 0", name="expected_size"),
    )

    universe_version: Mapped[str] = mapped_column(String(100), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    series_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    inception_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    expected_size: Mapped[int] = mapped_column(Integer, nullable=False)
    definition_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UniverseMembership(Base):
    __tablename__ = "universe_memberships"
    __table_args__ = (
        PrimaryKeyConstraint("universe_version", "asset_id"),
        UniqueConstraint("universe_version", "ordinal"),
        CheckConstraint("ordinal > 0", name="positive_ordinal"),
        CheckConstraint("included_to IS NULL OR included_to > included_from", name="included_range"),
    )

    universe_version: Mapped[str] = mapped_column(ForeignKey(f"{SCHEMA}.universe_versions.universe_version"))
    asset_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.assets.asset_id"))
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    included_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    included_to: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class SourcePolicyVersion(Base):
    __tablename__ = "source_policy_versions"
    __table_args__ = (
        CheckConstraint("status IN ('DRAFT','ACTIVE','RETIRED')", name="status"),
    )

    source_policy_version: Mapped[str] = mapped_column(String(100), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    definition_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SourcePolicyMapping(Base):
    __tablename__ = "source_policy_mappings"
    __table_args__ = (
        PrimaryKeyConstraint("source_policy_version", "asset_id"),
        ForeignKeyConstraint(
            ["mapping_id", "asset_id"],
            [f"{SCHEMA}.provider_mappings.mapping_id", f"{SCHEMA}.provider_mappings.asset_id"],
        ),
    )

    source_policy_version: Mapped[str] = mapped_column(ForeignKey(f"{SCHEMA}.source_policy_versions.source_policy_version"))
    asset_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.assets.asset_id"))
    mapping_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)


class SeriesDefinition(Base):
    __tablename__ = "series_definitions"
    __table_args__ = (
        CheckConstraint("series_kind IN ('LIVE','RESEARCH')", name="series_kind"),
        CheckConstraint("status IN ('CANDIDATE','ACTIVE','RETIRED')", name="status"),
        CheckConstraint(
            "series_kind <> 'LIVE' OR status <> 'ACTIVE' OR inception_at IS NOT NULL",
            name="live_requires_inception",
        ),
    )

    series_version: Mapped[str] = mapped_column(String(120), primary_key=True)
    series_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    universe_version: Mapped[str] = mapped_column(ForeignKey(f"{SCHEMA}.universe_versions.universe_version"), nullable=False)
    source_policy_version: Mapped[str] = mapped_column(ForeignKey(f"{SCHEMA}.source_policy_versions.source_policy_version"), nullable=False)
    formula_version: Mapped[str] = mapped_column(String(100), nullable=False)
    normalizer_version: Mapped[str] = mapped_column(String(100), nullable=False)
    methodology_version: Mapped[str] = mapped_column(String(100), nullable=False)
    inception_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    definition_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TimeframeCohort(Base):
    __tablename__ = "timeframe_cohorts"
    __table_args__ = (
        PrimaryKeyConstraint("series_version", "timeframe", "asset_id"),
        CheckConstraint("timeframe IN ('4h','1d','1w')", name="timeframe"),
        CheckConstraint("history_count_at_inception >= 0", name="history_count"),
    )

    series_version: Mapped[str] = mapped_column(ForeignKey(f"{SCHEMA}.series_definitions.series_version"))
    timeframe: Mapped[str] = mapped_column(String(4))
    asset_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.assets.asset_id"))
    included_in_denominator: Mapped[bool] = mapped_column(Boolean, nullable=False)
    history_count_at_inception: Mapped[int] = mapped_column(Integer, nullable=False)
    eligibility_reason: Mapped[str] = mapped_column(String(100), nullable=False)
    frozen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"
    __table_args__ = (
        CheckConstraint("run_type IN ('BOOTSTRAP','INCREMENTAL','RECOMPUTE','REPAIR')", name="run_type"),
        CheckConstraint("status IN ('PENDING','RUNNING','SUCCEEDED','FAILED')", name="status"),
        CheckConstraint("timeframe IS NULL OR timeframe IN ('4h','1d','1w')", name="timeframe"),
        CheckConstraint("target_end IS NULL OR target_start IS NULL OR target_end >= target_start", name="target_range"),
        CheckConstraint("attempt > 0", name="attempt"),
        CheckConstraint("expected_count >= 0 AND received_count >= 0 AND valid_count >= 0 AND quarantined_count >= 0", name="counts"),
        CheckConstraint(
            "valid_count + quarantined_count <= received_count", name="classified_count"
        ),
        CheckConstraint(
            "(status IN ('PENDING','RUNNING') AND finished_at IS NULL) OR "
            "(status IN ('SUCCEEDED','FAILED') AND finished_at IS NOT NULL)",
            name="finished_status",
        ),
    )

    run_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    run_type: Mapped[str] = mapped_column(String(20), nullable=False)
    series_version: Mapped[Optional[str]] = mapped_column(ForeignKey(f"{SCHEMA}.series_definitions.series_version"))
    source_id: Mapped[Optional[str]] = mapped_column(ForeignKey(f"{SCHEMA}.data_sources.source_id"))
    timeframe: Mapped[Optional[str]] = mapped_column(String(4))
    target_start: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    target_end: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    expected_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    received_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    valid_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    quarantined_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    scheduler_id: Mapped[Optional[str]] = mapped_column(String(100))
    code_sha: Mapped[str] = mapped_column(String(64), nullable=False)
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    error_summary: Mapped[Optional[str]] = mapped_column(Text)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class SourceArtifact(Base):
    __tablename__ = "source_artifacts"
    __table_args__ = (
        UniqueConstraint("source_version_id", "checksum"),
        CheckConstraint("range_end IS NULL OR range_start IS NULL OR range_end >= range_start", name="range"),
    )

    artifact_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.ingestion_runs.run_id"), nullable=False)
    source_version_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.source_versions.source_version_id"), nullable=False)
    artifact_type: Mapped[str] = mapped_column(String(40), nullable=False)
    uri: Mapped[str] = mapped_column(Text, nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    range_start: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    range_end: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CanonicalCandleRecord(Base):
    __tablename__ = "canonical_candles"
    __table_args__ = (
        UniqueConstraint("mapping_id", "timeframe", "open_time", "normalizer_version"),
        ForeignKeyConstraint(
            ["mapping_id", "asset_id", "source_id"],
            [
                f"{SCHEMA}.provider_mappings.mapping_id",
                f"{SCHEMA}.provider_mappings.asset_id",
                f"{SCHEMA}.provider_mappings.source_id",
            ],
        ),
        ForeignKeyConstraint(
            ["source_version_id", "source_id"],
            [
                f"{SCHEMA}.source_versions.source_version_id",
                f"{SCHEMA}.source_versions.source_id",
            ],
        ),
        CheckConstraint("timeframe IN ('4h','1d','1w')", name="timeframe"),
        CheckConstraint("status IN ('VALID','QUARANTINED')", name="status"),
        CheckConstraint("close_time > open_time", name="positive_duration"),
        CheckConstraint("open > 0 AND high > 0 AND low > 0 AND close > 0", name="positive_ohlc"),
        CheckConstraint("low <= open AND low <= close AND high >= open AND high >= close AND low <= high", name="ohlc_order"),
        CheckConstraint("base_volume IS NULL OR base_volume >= 0", name="base_volume"),
        CheckConstraint("quote_volume IS NULL OR quote_volume >= 0", name="quote_volume"),
        CheckConstraint("trade_count IS NULL OR trade_count >= 0", name="trade_count"),
        CheckConstraint(
            "(timeframe = '4h' AND close_time = open_time + INTERVAL '4 hours') OR "
            "(timeframe = '1d' AND close_time = open_time + INTERVAL '1 day') OR "
            "(timeframe = '1w' AND close_time = open_time + INTERVAL '7 days')",
            name="exact_duration",
        ),
        Index("ix_canonical_candles_asset_time", "asset_id", "timeframe", "open_time"),
    )

    candle_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    asset_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.assets.asset_id"), nullable=False)
    mapping_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    source_version_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    source_id: Mapped[str] = mapped_column(String(64), nullable=False)
    normalizer_version: Mapped[str] = mapped_column(String(100), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(4), nullable=False)
    open_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    close_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    open: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    high: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    low: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    close: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    base_volume: Mapped[Optional[Decimal]] = mapped_column(PRICE)
    quote_volume: Mapped[Optional[Decimal]] = mapped_column(PRICE)
    trade_count: Mapped[Optional[int]] = mapped_column(BigInteger)
    provider_closed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    source_payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    run_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.ingestion_runs.run_id"), nullable=False)


class IngestionError(Base):
    __tablename__ = "ingestion_errors"
    __table_args__ = (
        CheckConstraint("timeframe IS NULL OR timeframe IN ('4h','1d','1w')", name="timeframe"),
    )

    error_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.ingestion_runs.run_id"), nullable=False)
    source_id: Mapped[Optional[str]] = mapped_column(ForeignKey(f"{SCHEMA}.data_sources.source_id"))
    mapping_id: Mapped[Optional[UUID]] = mapped_column(ForeignKey(f"{SCHEMA}.provider_mappings.mapping_id"))
    asset_id: Mapped[Optional[UUID]] = mapped_column(ForeignKey(f"{SCHEMA}.assets.asset_id"))
    timeframe: Mapped[Optional[str]] = mapped_column(String(4))
    candle_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str] = mapped_column(String(100), nullable=False)
    retryable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    http_status: Mapped[Optional[int]] = mapped_column(Integer)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    payload_hash: Mapped[Optional[str]] = mapped_column(String(64))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class AssetIndicator(Base):
    __tablename__ = "asset_indicators"
    __table_args__ = (
        PrimaryKeyConstraint("series_version", "asset_id", "timeframe", "candle_time"),
        CheckConstraint("timeframe IN ('4h','1d','1w')", name="timeframe"),
        CheckConstraint("ema20_state IN ('AVAILABLE','WARMUP','UNAVAILABLE','GAP_BLOCKED')", name="ema20_state"),
        CheckConstraint("ema50_state IN ('AVAILABLE','WARMUP','UNAVAILABLE','GAP_BLOCKED')", name="ema50_state"),
        CheckConstraint("ema200_state IN ('AVAILABLE','WARMUP','UNAVAILABLE','GAP_BLOCKED')", name="ema200_state"),
        CheckConstraint("consecutive_count >= 0", name="consecutive_count"),
        CheckConstraint("(ema20_state = 'AVAILABLE') = (ema20 IS NOT NULL)", name="ema20_value_state"),
        CheckConstraint("(ema50_state = 'AVAILABLE') = (ema50 IS NOT NULL)", name="ema50_value_state"),
        CheckConstraint("(ema200_state = 'AVAILABLE') = (ema200 IS NOT NULL)", name="ema200_value_state"),
        ForeignKeyConstraint(
            ["mapping_id", "asset_id"],
            [f"{SCHEMA}.provider_mappings.mapping_id", f"{SCHEMA}.provider_mappings.asset_id"],
        ),
    )

    series_version: Mapped[str] = mapped_column(ForeignKey(f"{SCHEMA}.series_definitions.series_version"))
    universe_version: Mapped[str] = mapped_column(ForeignKey(f"{SCHEMA}.universe_versions.universe_version"), nullable=False)
    formula_version: Mapped[str] = mapped_column(String(100), nullable=False)
    normalizer_version: Mapped[str] = mapped_column(String(100), nullable=False)
    asset_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.assets.asset_id"))
    mapping_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(4))
    candle_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    candle_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.canonical_candles.candle_id"), nullable=False)
    close: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    ema20: Mapped[Optional[Decimal]] = mapped_column(PRICE)
    ema50: Mapped[Optional[Decimal]] = mapped_column(PRICE)
    ema200: Mapped[Optional[Decimal]] = mapped_column(PRICE)
    ema20_state: Mapped[str] = mapped_column(String(16), nullable=False)
    ema50_state: Mapped[str] = mapped_column(String(16), nullable=False)
    ema200_state: Mapped[str] = mapped_column(String(16), nullable=False)
    consecutive_count: Mapped[int] = mapped_column(Integer, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    run_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.ingestion_runs.run_id"), nullable=False)


class BreadthSnapshot(Base):
    __tablename__ = "breadth_snapshots"
    __table_args__ = (
        UniqueConstraint("series_version", "timeframe", "candle_time"),
        CheckConstraint("series_kind IN ('LIVE','RESEARCH')", name="series_kind"),
        CheckConstraint("timeframe IN ('4h','1d','1w')", name="timeframe"),
        CheckConstraint("status IN ('PUBLISHED','REJECTED','UNAVAILABLE')", name="status"),
        CheckConstraint("universe_size > 0 AND cohort_size > 0 AND cohort_size <= universe_size", name="sizes"),
        CheckConstraint("structural_coverage >= 0 AND structural_coverage <= 1", name="structural_coverage"),
        CheckConstraint("component_coverage >= 0 AND component_coverage <= 1", name="component_coverage"),
        CheckConstraint("data_quality_score >= 0 AND data_quality_score <= 100", name="data_quality"),
        CheckConstraint("data_quality_label IN ('HIGH','MEDIUM','LOW','UNAVAILABLE')", name="data_quality_label"),
        CheckConstraint(
            "(status = 'PUBLISHED' AND pct_above_ema20 IS NOT NULL AND pct_above_ema50 IS NOT NULL "
            "AND pct_above_ema200 IS NOT NULL AND breadth_score IS NOT NULL AND btc_close IS NOT NULL "
            "AND eth_close IS NOT NULL) OR (status <> 'PUBLISHED' AND pct_above_ema20 IS NULL "
            "AND pct_above_ema50 IS NULL AND pct_above_ema200 IS NULL AND breadth_score IS NULL)",
            name="atomic_components",
        ),
        Index("ix_breadth_snapshots_lookup", "series_version", "timeframe", "candle_time"),
    )

    snapshot_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    series_version: Mapped[str] = mapped_column(ForeignKey(f"{SCHEMA}.series_definitions.series_version"), nullable=False)
    series_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    universe_version: Mapped[str] = mapped_column(ForeignKey(f"{SCHEMA}.universe_versions.universe_version"), nullable=False)
    source_policy_version: Mapped[str] = mapped_column(ForeignKey(f"{SCHEMA}.source_policy_versions.source_policy_version"), nullable=False)
    formula_version: Mapped[str] = mapped_column(String(100), nullable=False)
    normalizer_version: Mapped[str] = mapped_column(String(100), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(4), nullable=False)
    candle_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    pct_above_ema20: Mapped[Optional[Decimal]] = mapped_column(PERCENT)
    pct_above_ema50: Mapped[Optional[Decimal]] = mapped_column(PERCENT)
    pct_above_ema200: Mapped[Optional[Decimal]] = mapped_column(PERCENT)
    breadth_score: Mapped[Optional[Decimal]] = mapped_column(PERCENT)
    numerator20: Mapped[Optional[int]] = mapped_column(Integer)
    numerator50: Mapped[Optional[int]] = mapped_column(Integer)
    numerator200: Mapped[Optional[int]] = mapped_column(Integer)
    universe_size: Mapped[int] = mapped_column(Integer, nullable=False)
    cohort_size: Mapped[int] = mapped_column(Integer, nullable=False)
    structural_coverage: Mapped[Decimal] = mapped_column(Numeric(9, 8), nullable=False)
    component_coverage: Mapped[Decimal] = mapped_column(Numeric(9, 8), nullable=False)
    data_quality_score: Mapped[Decimal] = mapped_column(Numeric(5, 1), nullable=False)
    data_quality_label: Mapped[str] = mapped_column(String(20), nullable=False)
    btc_close: Mapped[Optional[Decimal]] = mapped_column(PRICE)
    eth_close: Mapped[Optional[Decimal]] = mapped_column(PRICE)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    run_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.ingestion_runs.run_id"), nullable=False)


class SnapshotMember(Base):
    __tablename__ = "snapshot_members"
    __table_args__ = (
        PrimaryKeyConstraint("snapshot_id", "asset_id"),
        CheckConstraint("state20 IN ('ABOVE','BELOW','UNAVAILABLE')", name="state20"),
        CheckConstraint("state50 IN ('ABOVE','BELOW','UNAVAILABLE')", name="state50"),
        CheckConstraint("state200 IN ('ABOVE','BELOW','UNAVAILABLE')", name="state200"),
        CheckConstraint("(state20 = 'ABOVE' AND above20 IS TRUE) OR (state20 = 'BELOW' AND above20 IS FALSE) OR (state20 = 'UNAVAILABLE' AND above20 IS NULL)", name="state20_boolean"),
        CheckConstraint("(state50 = 'ABOVE' AND above50 IS TRUE) OR (state50 = 'BELOW' AND above50 IS FALSE) OR (state50 = 'UNAVAILABLE' AND above50 IS NULL)", name="state50_boolean"),
        CheckConstraint("(state200 = 'ABOVE' AND above200 IS TRUE) OR (state200 = 'BELOW' AND above200 IS FALSE) OR (state200 = 'UNAVAILABLE' AND above200 IS NULL)", name="state200_boolean"),
        ForeignKeyConstraint(
            ["mapping_id", "asset_id", "source_id"],
            [
                f"{SCHEMA}.provider_mappings.mapping_id",
                f"{SCHEMA}.provider_mappings.asset_id",
                f"{SCHEMA}.provider_mappings.source_id",
            ],
        ),
    )

    snapshot_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.breadth_snapshots.snapshot_id", ondelete="CASCADE"))
    asset_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.assets.asset_id"))
    mapping_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    source_id: Mapped[str] = mapped_column(String(64), nullable=False)
    close: Mapped[Optional[Decimal]] = mapped_column(PRICE)
    ema20: Mapped[Optional[Decimal]] = mapped_column(PRICE)
    ema50: Mapped[Optional[Decimal]] = mapped_column(PRICE)
    ema200: Mapped[Optional[Decimal]] = mapped_column(PRICE)
    above20: Mapped[Optional[bool]] = mapped_column(Boolean)
    above50: Mapped[Optional[bool]] = mapped_column(Boolean)
    above200: Mapped[Optional[bool]] = mapped_column(Boolean)
    state20: Mapped[str] = mapped_column(String(16), nullable=False)
    state50: Mapped[str] = mapped_column(String(16), nullable=False)
    state200: Mapped[str] = mapped_column(String(16), nullable=False)
    included_in_denominator: Mapped[bool] = mapped_column(Boolean, nullable=False)
    exclusion_reason: Mapped[Optional[str]] = mapped_column(String(100))


class ScannerStateRecord(Base):
    __tablename__ = "scanner_state"
    __table_args__ = (
        PrimaryKeyConstraint("series_version", "timeframe", "asset_id"),
        CheckConstraint("timeframe IN ('4h','1d','1w')", name="timeframe"),
        CheckConstraint("state20 IN ('ABOVE','BELOW','UNAVAILABLE')", name="state20"),
        CheckConstraint("state50 IN ('ABOVE','BELOW','UNAVAILABLE')", name="state50"),
        CheckConstraint("state200 IN ('ABOVE','BELOW','UNAVAILABLE')", name="state200"),
        CheckConstraint("(state20 = 'UNAVAILABLE') = (ema20 IS NULL)", name="state20_value"),
        CheckConstraint("(state50 = 'UNAVAILABLE') = (ema50 IS NULL)", name="state50_value"),
        CheckConstraint("(state200 = 'UNAVAILABLE') = (ema200 IS NULL)", name="state200_value"),
        ForeignKeyConstraint(
            ["mapping_id", "asset_id", "source_id"],
            [
                f"{SCHEMA}.provider_mappings.mapping_id",
                f"{SCHEMA}.provider_mappings.asset_id",
                f"{SCHEMA}.provider_mappings.source_id",
            ],
        ),
    )

    series_version: Mapped[str] = mapped_column(ForeignKey(f"{SCHEMA}.series_definitions.series_version"))
    timeframe: Mapped[str] = mapped_column(String(4))
    asset_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.assets.asset_id"))
    candle_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    price: Mapped[Optional[Decimal]] = mapped_column(PRICE)
    ema20: Mapped[Optional[Decimal]] = mapped_column(PRICE)
    ema50: Mapped[Optional[Decimal]] = mapped_column(PRICE)
    ema200: Mapped[Optional[Decimal]] = mapped_column(PRICE)
    state20: Mapped[str] = mapped_column(String(16), nullable=False)
    state50: Mapped[str] = mapped_column(String(16), nullable=False)
    state200: Mapped[str] = mapped_column(String(16), nullable=False)
    included_in_breadth: Mapped[bool] = mapped_column(Boolean, nullable=False)
    mapping_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    source_id: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot_id: Mapped[Optional[UUID]] = mapped_column(ForeignKey(f"{SCHEMA}.breadth_snapshots.snapshot_id", ondelete="SET NULL"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
