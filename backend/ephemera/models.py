"""SQLAlchemy models.

All times are UTC. `UTCDateTime` rejects naive datetimes on the way in and returns aware UTC
datetimes on the way out; the database column itself holds naive UTC.
"""

from datetime import UTC, datetime

from sqlalchemy import (
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
