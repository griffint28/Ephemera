"""SQLAlchemy models.

All times are UTC. `UTCDateTime` rejects naive datetimes on the way in and returns aware UTC
datetimes on the way out; the database column itself holds naive UTC.
"""

from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Double,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
)
from sqlalchemy.dialects import mysql
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class NaiveDatetimeError(ValueError):
    pass


class UTCDateTime(TypeDecorator[datetime]):
    """Timezone-aware UTC in Python, naive UTC (microsecond precision) in the database."""

    impl = DateTime
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect):  # type: ignore[no-untyped-def]
        if dialect.name in ("mysql", "mariadb"):
            return dialect.type_descriptor(mysql.DATETIME(fsp=6))
        return dialect.type_descriptor(DateTime())

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise NaiveDatetimeError(f"naive datetime {value!r}: Ephemera stores UTC only")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Satellite(Base):
    __tablename__ = "satellites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    norad_id: Mapped[int] = mapped_column(Integer, unique=True)
    code: Mapped[str] = mapped_column(String(8), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    operator: Mapped[str] = mapped_column(String(100))
    # CelesTrak fetch bookkeeping: the 2 h floor counts every attempt, the 12 h cache only
    # successful ones.
    last_fetch_attempt_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_fetch_success_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    # Simulated workload. ILLUSTRATIVE defaults from config, not spacecraft specifications.
    storage_capacity_gb: Mapped[float] = mapped_column(Double)
    generation_rate_gb_per_hour: Mapped[float] = mapped_column(Double)
    downlink_rate_gb_per_min: Mapped[float] = mapped_column(Double)

    elements: Mapped[list["OrbitalElements"]] = relationship(back_populates="satellite")

    def __repr__(self) -> str:
        return f"<Satellite {self.code} {self.norad_id}>"


class Station(Base):
    __tablename__ = "stations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(8), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    operator: Mapped[str] = mapped_column(String(100))
    latitude_deg: Mapped[float] = mapped_column(Double)
    longitude_deg: Mapped[float] = mapped_column(Double)
    altitude_m: Mapped[float] = mapped_column(Double)
    min_elevation_deg: Mapped[float] = mapped_column(Double)
    timezone: Mapped[str] = mapped_column(String(64))  # display only

    def __repr__(self) -> str:
        return f"<Station {self.code}>"


class OrbitalElements(Base):
    """One CelesTrak GP element set (OMM) as fetched. Never overwritten; new epochs add rows."""

    __tablename__ = "orbital_elements"
    __table_args__ = (UniqueConstraint("satellite_id", "epoch"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    satellite_id: Mapped[int] = mapped_column(ForeignKey("satellites.id"))
    epoch: Mapped[datetime] = mapped_column(UTCDateTime())
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime())
    source: Mapped[str] = mapped_column(String(32))
    omm_json: Mapped[str] = mapped_column(Text)  # the GP record exactly as CelesTrak sent it

    satellite: Mapped[Satellite] = relationship(back_populates="elements")


class Pass(Base):
    """A predicted pass of one satellite over one station, above that station's mask."""

    __tablename__ = "passes"
    __table_args__ = (
        UniqueConstraint("satellite_id", "station_id", "rise_time"),
        Index("ix_passes_station_id_rise_time", "station_id", "rise_time"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    satellite_id: Mapped[int] = mapped_column(ForeignKey("satellites.id"))
    station_id: Mapped[int] = mapped_column(ForeignKey("stations.id"))
    orbital_elements_id: Mapped[int] = mapped_column(ForeignKey("orbital_elements.id"))

    rise_time: Mapped[datetime] = mapped_column(UTCDateTime())
    peak_time: Mapped[datetime] = mapped_column(UTCDateTime())
    set_time: Mapped[datetime] = mapped_column(UTCDateTime())
    duration_s: Mapped[float] = mapped_column(Double)
    peak_elevation_deg: Mapped[float] = mapped_column(Double)
    rise_azimuth_deg: Mapped[float] = mapped_column(Double)
    peak_azimuth_deg: Mapped[float] = mapped_column(Double)
    set_azimuth_deg: Mapped[float] = mapped_column(Double)
    min_elevation_deg: Mapped[float] = mapped_column(Double)  # the mask used
    computed_at: Mapped[datetime] = mapped_column(UTCDateTime())

    satellite: Mapped[Satellite] = relationship()
    station: Mapped[Station] = relationship()
    orbital_elements: Mapped[OrbitalElements] = relationship()


class SimulationRun(Base):
    """One seeded data simulation over a window. Its chunks are the demand a scheduler sees."""

    __tablename__ = "simulation_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    seed: Mapped[int] = mapped_column(Integer)
    window_start: Mapped[datetime] = mapped_column(UTCDateTime())
    window_end: Mapped[datetime] = mapped_column(UTCDateTime())
    routine_chunk_minutes: Mapped[float] = mapped_column(Double)
    urgent_events_per_day: Mapped[float] = mapped_column(Double)
    urgent_chunk_gb: Mapped[float] = mapped_column(Double)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())

    chunks: Mapped[list["DataChunk"]] = relationship(back_populates="simulation_run", cascade="all, delete-orphan")
    schedule_runs: Mapped[list["ScheduleRun"]] = relationship(
        back_populates="simulation_run", cascade="all, delete-orphan"
    )


class DataChunk(Base):
    """A piece of simulated data created onboard a satellite."""

    __tablename__ = "data_chunks"
    __table_args__ = (Index("ix_data_chunks_simulation_run_id_created_at", "simulation_run_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    simulation_run_id: Mapped[int] = mapped_column(ForeignKey("simulation_runs.id"))
    satellite_id: Mapped[int] = mapped_column(ForeignKey("satellites.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    size_gb: Mapped[float] = mapped_column(Double)
    urgent: Mapped[bool] = mapped_column(Boolean)

    simulation_run: Mapped[SimulationRun] = relationship(back_populates="chunks")
    satellite: Mapped[Satellite] = relationship()


class ScheduleRun(Base):
    """One scheduler applied to one simulation. Metrics are recomputed from it, never stored."""

    __tablename__ = "schedule_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    simulation_run_id: Mapped[int] = mapped_column(ForeignKey("simulation_runs.id"))
    scheduler: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())

    simulation_run: Mapped[SimulationRun] = relationship(back_populates="schedule_runs")
    assignments: Mapped[list["Assignment"]] = relationship(
        back_populates="schedule_run", cascade="all, delete-orphan"
    )


class Assignment(Base):
    """A pass a schedule run chose to use."""

    __tablename__ = "assignments"
    __table_args__ = (UniqueConstraint("schedule_run_id", "pass_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    schedule_run_id: Mapped[int] = mapped_column(ForeignKey("schedule_runs.id"))
    pass_id: Mapped[int] = mapped_column(ForeignKey("passes.id"))

    schedule_run: Mapped[ScheduleRun] = relationship(back_populates="assignments")
    pass_: Mapped[Pass] = relationship()
