"""Persisted target-selection contract shared by the UI and stream servers."""

from __future__ import annotations

import logging
from uuid import UUID

import numpy as np
from sqlalchemy import select

from src.db.database import Database
from src.db.models import Target, TargetEmbedding
from src.recognition.target_matcher import target_manager

logger = logging.getLogger("datt.target_selection")


def set_persisted_target_selection(target_id: str, selected: bool) -> bool:
    """Set selection on an active persisted target and refresh the runtime cache.

    ``reference_metadata.selected`` is the source of truth. The matcher cache is
    restored from the persistent target and embedding records.
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

            runtime_target = target_manager.get_target(str(record.id))
            if runtime_target is None:
                te = session.scalars(
                    select(TargetEmbedding)
                    .where(TargetEmbedding.target_id == record.id)
                    .order_by(TargetEmbedding.created_at.desc())
                ).first()
                face_emb = None
                emb_model = "adaface_ir50_ms1mv2"
                if te is not None and te.embedding is not None:
                    face_emb = np.asarray(te.embedding, dtype=np.float32)
                    emb_model = te.model_name or "adaface_ir50_ms1mv2"
                elif record.embedding is not None:
                    face_emb = np.asarray(record.embedding, dtype=np.float32)

                runtime_target = target_manager.add_target_from_db(
                    target_id=str(record.id),
                    name=record.name,
                    face_embedding=face_emb,
                    clothing_color=metadata.get("clothing_color"),
                    face_threshold=float(metadata.get("threshold", 0.45)),
                    source_image_path=record.image_path,
                    db_id=str(record.id),
                    embedding_model=emb_model,
                    is_selected=bool(selected),
                )
            runtime_target.is_selected = bool(selected)
        return True
    finally:
        db.dispose()


def restore_persisted_targets() -> int:
    """Restore all active persisted targets and their embeddings into target_manager.

    Guarantees that active, selected targets are immediately available in memory
    before processing video frames, with zero DB queries per frame.
    Returns the count of successfully restored targets.
    """
    db = Database()
    try:
        with db.transaction() as session:
            active_targets = list(session.scalars(select(Target).where(Target.active == True)).all())
            if not active_targets:
                logger.info("[TARGET_RESTORE] No active targets found in database.")
                return 0

            target_ids = [t.id for t in active_targets]
            embeddings = session.scalars(
                select(TargetEmbedding)
                .where(TargetEmbedding.target_id.in_(target_ids))
                .order_by(TargetEmbedding.created_at.desc())
            ).all()

            # Group latest embedding per target
            te_by_target: dict[UUID, TargetEmbedding] = {}
            for te in embeddings:
                if te.target_id not in te_by_target:
                    te_by_target[te.target_id] = te

            restored_count = 0
            for record in active_targets:
                metadata = dict(record.reference_metadata or {})
                is_selected = bool(metadata.get("selected", True))
                threshold = float(metadata.get("threshold", 0.45))
                clothing_color = metadata.get("clothing_color")
                source_image_path = record.image_path

                te = te_by_target.get(record.id)
                face_emb = None
                model_name = "adaface_ir50_ms1mv2"
                if te is not None and te.embedding is not None:
                    face_emb = np.asarray(te.embedding, dtype=np.float32)
                    model_name = te.model_name or "adaface_ir50_ms1mv2"
                elif record.embedding is not None:
                    face_emb = np.asarray(record.embedding, dtype=np.float32)

                target_manager.add_target_from_db(
                    target_id=str(record.id),
                    name=record.name,
                    face_embedding=face_emb,
                    clothing_color=clothing_color,
                    face_threshold=threshold,
                    source_image_path=source_image_path,
                    db_id=str(record.id),
                    embedding_model=model_name,
                    is_selected=is_selected,
                )
                restored_count += 1

            logger.info(
                "[TARGET_RESTORE] Restored %d active target(s) into memory (selected=%d)",
                restored_count,
                sum(1 for t in target_manager.list_targets() if t.is_selected),
            )
            return restored_count
    except Exception as exc:
        logger.warning("[TARGET_RESTORE] Target restoration failed or DB unavailable: %s", exc)
        return 0
    finally:
        db.dispose()

