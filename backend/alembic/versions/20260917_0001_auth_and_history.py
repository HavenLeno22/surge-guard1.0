"""Operator accounts, sign-in sessions and aggregated observation history.

Revision ID: 0001_auth_and_history
Revises:
Created: 2026-09-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0001_auth_and_history"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply this migration."""
    op.create_table(
        "user_account",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("display_name", sa.String(length=80), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("role IN ('ADMIN', 'OPERATOR')", name="ck_user_account_role"),
        sa.PrimaryKeyConstraint("id", name="pk_user_account"),
        sa.UniqueConstraint("email", name="uq_user_account_email"),
    )

    op.create_table(
        "user_session",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_agent", sa.String(length=255), nullable=True),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user_account.id"],
            name="fk_user_session_user_id_user_account",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_user_session"),
        sa.UniqueConstraint("token_hash", name="uq_user_session_token_hash"),
    )
    op.create_index("ix_user_session_user_id", "user_session", ["user_id"], unique=False)

    op.create_table(
        "observation_bucket",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("camera_id", sa.String(length=32), nullable=False),
        sa.Column("bucket_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("bucket_seconds", sa.Integer(), nullable=False),
        sa.Column("source_mode", sa.String(length=8), nullable=False),
        sa.Column("samples", sa.Integer(), nullable=False),
        sa.Column("degraded_samples", sa.Integer(), nullable=False),
        sa.Column("csi_mean", sa.Float(), nullable=True),
        sa.Column("csi_min", sa.Float(), nullable=True),
        sa.Column("csi_max", sa.Float(), nullable=True),
        sa.Column("status_worst", sa.String(length=24), nullable=True),
        sa.Column("status_last", sa.String(length=24), nullable=True),
        sa.Column("status_samples", sa.JSON(), nullable=True),
        sa.Column("confidence_mean", sa.Float(), nullable=True),
        sa.Column("people_mean", sa.Float(), nullable=True),
        sa.Column("people_max", sa.Integer(), nullable=True),
        sa.Column("estimated_samples", sa.Integer(), nullable=False),
        sa.Column("density_max", sa.Float(), nullable=True),
        sa.Column("density_is_metric", sa.Boolean(), nullable=True),
        sa.Column("queue_length_mean", sa.Float(), nullable=True),
        sa.Column("queue_length_max", sa.Integer(), nullable=True),
        sa.Column("wait_minutes_mean", sa.Float(), nullable=True),
        sa.Column("wait_minutes_max", sa.Float(), nullable=True),
        sa.Column("arrival_rate_mean", sa.Float(), nullable=True),
        sa.Column("service_rate_mean", sa.Float(), nullable=True),
        sa.Column("cameras_contributing_min", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_observation_bucket"),
        sa.UniqueConstraint(
            "camera_id",
            "bucket_start",
            "bucket_seconds",
            "source_mode",
            name="uq_observation_bucket_camera_id",
        ),
    )
    op.create_index(
        "ix_observation_bucket_camera_id",
        "observation_bucket",
        ["camera_id", "bucket_start"],
        unique=False,
    )


def downgrade() -> None:
    """Revert this migration."""
    op.drop_index("ix_observation_bucket_camera_id", table_name="observation_bucket")
    op.drop_table("observation_bucket")
    op.drop_index("ix_user_session_user_id", table_name="user_session")
    op.drop_table("user_session")
    op.drop_table("user_account")
