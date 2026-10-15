"""Persisted target-selection contract shared by the UI and stream servers."""

from __future__ import annotations

from uuid import UUID

from src.db.database import Database
from src.db.models import Target, TargetEmbedding
from sqlalchemy import select
import numpy as np
from src.recognition.target_matcher import target_manager


def set_persisted_target_selection(target_id: str, selected: bool) -> bool:
    """Set selection on an active persisted target and refresh the runtime cache.

    ``reference_metadata.selected`` is the source of truth.  The matcher cache is
    intentionally only a runtime projection and may be empty after a restart.
    """
    try:
        target_uuid = UUID(str(target_id))
    except (TypeError, ValueError):
        return False

    db = Database()
    try:
        with db.transaction() as session:
            record = session.get(Target, target_uuid)
            if record is None or not record.active:
                return False
            metadata = dict(record.reference_metadata or {})
            metadata["selected"] = bool(selected)
            record.reference_metadata = metadata

            embedding_record = session.scalar(select(TargetEmbedding).where(
                TargetEmbedding.target_id == record.id
            ).order_by(TargetEmbedding.created_at.desc()).limit(1))
            face_embedding = np.asarray(embedding_record.embedding, dtype=np.float32) if embedding_record is not None else None
            model_name = embedding_record.model_name if embedding_record is not None else 'unavailable'
            runtime_target = target_manager.get_target(str(record.id))
            if runtime_target is None:
                runtime_target = target_manager.add_target_from_db(
                    target_id=str(record.id),
                    name=record.name,
                    face_embedding=face_embedding,
                    embedding_model=model_name,
                    clothing_color=metadata.get("clothing_color"),
                    face_threshold=float(metadata.get("threshold", 0.45)),
                    source_image_path=record.image_path,
                    db_id=str(record.id),
                )
            elif runtime_target.face_embedding is None and face_embedding is not None:
                runtime_target = target_manager.add_target_from_db(
                    target_id=str(record.id), name=record.name,
                    face_embedding=face_embedding, embedding_model=model_name,
                    clothing_color=metadata.get("clothing_color"),
                    face_threshold=float(metadata.get("threshold", 0.45)),
                    source_image_path=record.image_path, db_id=str(record.id),
                )
            runtime_target.is_selected = bool(selected)
        return True
    finally:
        db.dispose()
