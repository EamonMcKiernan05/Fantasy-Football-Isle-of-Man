"""add_fixture_kickoff_time_and_check_attempts

Revision ID: e82504a432d4
Revises: 227b8598a382
Create Date: 2026-05-27 18:29:21.255632

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e82504a432d4"
down_revision: Union[str, None] = "227b8598a382"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("fixtures", sa.Column("kickoff_time", sa.Time, nullable=True))
    op.add_column("fixtures", sa.Column("result_check_attempts", sa.Integer, server_default="0"))


def downgrade() -> None:
    op.drop_column("fixtures", "result_check_attempts")
    op.drop_column("fixtures", "kickoff_time")
