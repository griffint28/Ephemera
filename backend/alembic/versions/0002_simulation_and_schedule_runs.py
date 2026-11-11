"""Simulation and schedule runs: satellite workload columns, simulation_runs, data_chunks,
schedule_runs, assignments.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UTC_DATETIME = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql", "mariadb")

# Existing rows need a value; seed-fleet overwrites it from config straight away. The models
# carry no server default on purpose: the numbers come from config, not from the schema.
_PLACEHOLDER = sa.text("0")


def upgrade() -> None:
    with op.batch_alter_table("satellites") as batch:
        batch.add_column(sa.Column("storage_capacity_gb", sa.Double(), nullable=False, server_default=_PLACEHOLDER))
        batch.add_column(
            sa.Column("generation_rate_gb_per_hour", sa.Double(), nullable=False, server_default=_PLACEHOLDER)
        )
        batch.add_column(
            sa.Column("downlink_rate_gb_per_min", sa.Double(), nullable=False, server_default=_PLACEHOLDER)
        )
    with op.batch_alter_table("satellites") as batch:
        for name in ("storage_capacity_gb", "generation_rate_gb_per_hour", "downlink_rate_gb_per_min"):
            batch.alter_column(name, server_default=None, existing_type=sa.Double(), existing_nullable=False)

    op.create_table(
        "simulation_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column("window_start", UTC_DATETIME, nullable=False),
        sa.Column("window_end", UTC_DATETIME, nullable=False),
        sa.Column("routine_chunk_minutes", sa.Double(), nullable=False),
        sa.Column("urgent_events_per_day", sa.Double(), nullable=False),
        sa.Column("urgent_chunk_gb", sa.Double(), nullable=False),
        sa.Column("created_at", UTC_DATETIME, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_simulation_runs"),
    )
    op.create_table(
        "data_chunks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("simulation_run_id", sa.Integer(), nullable=False),
        sa.Column("satellite_id", sa.Integer(), nullable=False),
        sa.Column("created_at", UTC_DATETIME, nullable=False),
        sa.Column("size_gb", sa.Double(), nullable=False),
        sa.Column("urgent", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_data_chunks"),
        sa.ForeignKeyConstraint(
            ["simulation_run_id"], ["simulation_runs.id"], name="fk_data_chunks_simulation_run_id_simulation_runs"
        ),
        sa.ForeignKeyConstraint(["satellite_id"], ["satellites.id"], name="fk_data_chunks_satellite_id_satellites"),
    )
    op.create_index(
        "ix_data_chunks_simulation_run_id_created_at", "data_chunks", ["simulation_run_id", "created_at"]
    )
    op.create_table(
        "schedule_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("simulation_run_id", sa.Integer(), nullable=False),
        sa.Column("scheduler", sa.String(32), nullable=False),
        sa.Column("created_at", UTC_DATETIME, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_schedule_runs"),
        sa.ForeignKeyConstraint(
            ["simulation_run_id"], ["simulation_runs.id"], name="fk_schedule_runs_simulation_run_id_simulation_runs"
        ),
    )
    op.create_table(
        "assignments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("schedule_run_id", sa.Integer(), nullable=False),
        sa.Column("pass_id", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_assignments"),
        sa.ForeignKeyConstraint(
            ["schedule_run_id"], ["schedule_runs.id"], name="fk_assignments_schedule_run_id_schedule_runs"
        ),
        sa.ForeignKeyConstraint(["pass_id"], ["passes.id"], name="fk_assignments_pass_id_passes"),
        sa.UniqueConstraint("schedule_run_id", "pass_id", name="uq_assignments_schedule_run_id_pass_id"),
    )


def downgrade() -> None:
    op.drop_table("assignments")
    op.drop_table("schedule_runs")
    # Dropping the table drops its indexes. MariaDB refuses to drop the index on its own because
    # it backs the simulation_run_id foreign key.
    op.drop_table("data_chunks")
    op.drop_table("simulation_runs")
    with op.batch_alter_table("satellites") as batch:
        batch.drop_column("downlink_rate_gb_per_min")
        batch.drop_column("generation_rate_gb_per_hour")
        batch.drop_column("storage_capacity_gb")
