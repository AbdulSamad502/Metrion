"""investigation_attachment: files the seller attaches to a CEO conversation

Spec §6.34 (2026-10-10). The bytes are stored tenant-scoped (FORCE RLS) with their sha256 and the type DETECTED FROM THE CONTENT (the declared name or type is never
trusted). `extracted_text` is what the reader could pull out (PDF text, CSV / XLSX cells); it is UNTRUSTED data, quoted to the composer only inside delimited evidence
and never a figure. Append-only for the app role (SELECT, INSERT): an attachment is evidence of what the seller showed the CEO and is not rewritten or deleted.

Revision ID: 20261010_0010
Revises: 20261010_0009
Create Date: 2026-10-10
"""
from __future__ import annotations

from alembic import op

revision = "20261010_0010"
down_revision = "20261010_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE investigation_attachment (
          id                uuid primary key default gen_random_uuid(),
          tenant_id         uuid not null,
          investigation_id  uuid not null references investigation(id),
          filename          text not null,
          detected_type     text not null,            -- PNG | JPEG | WEBP | PDF | CSV | XLSX (from the content, not the name)
          byte_size         integer not null,
          sha256            text not null,
          content           bytea not null,
          extraction_status text not null,            -- OK | NOT_READ | FAILED
          extraction_note   text,                     -- plain words: why it could not be read, or what was cut off
          extracted_text    text,                     -- untrusted quoted data, bounded
          created_by        uuid,
          created_at        timestamptz not null default now(),
          CONSTRAINT investigation_attachment_type_check CHECK (detected_type IN ('PNG', 'JPEG', 'WEBP', 'PDF', 'CSV', 'XLSX')),
          CONSTRAINT investigation_attachment_status_check CHECK (extraction_status IN ('OK', 'NOT_READ', 'FAILED')),
          CONSTRAINT investigation_attachment_size_check CHECK (byte_size > 0)
        );
        CREATE INDEX investigation_attachment_investigation_idx ON investigation_attachment (investigation_id, created_at);
        ALTER TABLE investigation_attachment ENABLE ROW LEVEL SECURITY;
        ALTER TABLE investigation_attachment FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON investigation_attachment
          USING      (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
          WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);
        GRANT SELECT, INSERT ON investigation_attachment TO metrion_app;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS investigation_attachment;")
