"""Orbits and passes: satellites, stations, orbital element sets, passes.

Revision ID: 0001
Revises:
Create Date: 2026-11-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Naive UTC with microseconds on MariaDB; the models attach and enforce the UTC zone.
UTC_DATETIME = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql", "mariadb")


def upgrade() -> None:
    op.create_table(
        "satellites",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("norad_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(8), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("operator", sa.String(100), nullable=False),
        sa.Column("last_fetch_attempt_at", UTC_DATETIME, nullable=True),
        sa.Column("last_fetch_success_at", UTC_DATETIME, nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_satellites"),
        sa.UniqueConstraint("norad_id", name="uq_satellites_norad_id"),
        sa.UniqueConstraint("code", name="uq_satellites_code"),
    )
    op.create_table(
        "stations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(8), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("operator", sa.String(100), nullable=False),
        sa.Column("latitude_deg", sa.Double(), nullable=False),
        sa.Column("longitude_deg", sa.Double(), nullable=False),
        sa.Column("altitude_m", sa.Double(), nullable=False),
        sa.Column("min_elevation_deg", sa.Double(), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_stations"),
        sa.UniqueConstraint("code", name="uq_stations_code"),
    )
    op.create_table(
        "orbital_elements",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("satellite_id", sa.Integer(), nullable=False),
        sa.Column("epoch", UTC_DATETIME, nullable=False),
        sa.Column("fetched_at", UTC_DATETIME, nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("omm_json", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_orbital_elements"),
        sa.ForeignKeyConstraint(
            ["satellite_id"], ["satellites.id"], name="fk_orbital_elements_satellite_id_satellites"
        ),
        sa.UniqueConstraint("satellite_id", "epoch", name="uq_orbital_elements_satellite_id_epoch"),
    )
    op.create_table(
        "passes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("satellite_id", sa.Integer(), nullable=False),
        sa.Column("station_id", sa.Integer(), nullable=False),
        sa.Column("orbital_elements_id", sa.Integer(), nullable=False),
        sa.Column("rise_time", UTC_DATETIME, nullable=False),
        sa.Column("peak_time", UTC_DATETIME, nullable=False),
        sa.Column("set_time", UTC_DATETIME, nullable=False),
        sa.Column("duration_s", sa.Double(), nullable=False),
        sa.Column("peak_elevation_deg", sa.Double(), nullable=False),
        sa.Column("rise_azimuth_deg", sa.Double(), nullable=False),
        sa.Column("peak_azimuth_deg", sa.Double(), nullable=False),
        sa.Column("set_azimuth_deg", sa.Double(), nullable=False),
        sa.Column("min_elevation_deg", sa.Double(), nullable=False),
        sa.Column("computed_at", UTC_DATETIME, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_passes"),
        sa.ForeignKeyConstraint(["satellite_id"], ["satellites.id"], name="fk_passes_satellite_id_satellites"),
        sa.ForeignKeyConstraint(["station_id"], ["stations.id"], name="fk_passes_station_id_stations"),
        sa.ForeignKeyConstraint(
            ["orbital_elements_id"],
            ["orbital_elements.id"],
            name="fk_passes_orbital_elements_id_orbital_elements",
        ),
        sa.UniqueConstraint(
            "satellite_id", "station_id", "rise_time", name="uq_passes_satellite_id_station_id_rise_time"
        ),
    )
    op.create_index("ix_passes_station_id_rise_time", "passes", ["station_id", "rise_time"])


def downgrade() -> None:
    # Dropping the table drops its indexes. MariaDB refuses to drop ix_passes_station_id_rise_time
    # on its own because it backs the station_id foreign key.
    op.drop_table("passes")
    op.drop_table("orbital_elements")
    op.drop_table("stations")
    op.drop_table("satellites")
