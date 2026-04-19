"""
Servizio centralizzato per razionalizzazione tassonomia (etichette/categorie).
"""

from __future__ import annotations

import json
import unicodedata
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from models import (
    db,
    Category,
    Label,
    CellAnnotation,
    TaxonomyAlias,
    TaxonomyMergeAudit,
)


class TaxonomyService:
    def __init__(self, session=None):
        self.session = session or db.session

    @staticmethod
    def normalize_name(value: str) -> str:
        """Normalizza un nome per matching tassonomico."""
        if not value:
            return ""

        value = unicodedata.normalize("NFKD", value.strip().lower())
        value = "".join(ch for ch in value if not unicodedata.combining(ch))
        value = value.replace(" ", "").replace("-", "").replace("_", "")
        return value

    def _canonical_labels(self):
        return Label.query.filter(
            Label.is_active == True,  # noqa: E712
            Label.merged_into_label_id.is_(None)
        )

    def _canonical_categories(self):
        return Category.query.filter(
            Category.is_active == True,  # noqa: E712
            Category.merged_into_category_id.is_(None)
        )

    def find_name_conflict(self, entity_type: str, name: str, exclude_id: Optional[int] = None) -> Optional[Dict]:
        """
        Verifica collisioni contro canonicali attivi e alias attivi.
        entity_type: 'label' | 'category'
        """
        normalized = self.normalize_name(name)
        if not normalized:
            return None

        if entity_type == "label":
            canonical_entities = self._canonical_labels().all()
        elif entity_type == "category":
            canonical_entities = self._canonical_categories().all()
        else:
            raise ValueError(f"entity_type non supportato: {entity_type}")

        for entity in canonical_entities:
            if exclude_id and entity.id == exclude_id:
                continue
            if self.normalize_name(entity.name) == normalized:
                return {
                    "type": "canonical",
                    "entity_type": entity_type,
                    "id": entity.id,
                    "name": entity.name,
                }

        alias_query = TaxonomyAlias.query.filter_by(
            entity_type=entity_type,
            alias_normalized=normalized,
            is_active=True
        )
        existing_alias = alias_query.first()
        if existing_alias:
            if exclude_id and existing_alias.canonical_id == exclude_id:
                return None
            return {
                "type": "alias",
                "entity_type": entity_type,
                "id": existing_alias.id,
                "name": existing_alias.alias_name,
                "canonical_id": existing_alias.canonical_id,
            }

        return None

    def ensure_name_allowed(self, entity_type: str, name: str, exclude_id: Optional[int] = None) -> Tuple[bool, Optional[str]]:
        conflict = self.find_name_conflict(entity_type, name, exclude_id=exclude_id)
        if not conflict:
            return True, None

        if conflict["type"] == "canonical":
            return False, (
                f"Nome non consentito: collisione con {entity_type} canonica "
                f'"{conflict["name"]}" (matching normalizzato).'
            )

        return False, (
            f"Nome non consentito: coincide con alias attivo "
            f'"{conflict["name"]}" della tassonomia.'
        )

    def create_or_activate_alias(
        self,
        entity_type: str,
        alias_name: str,
        canonical_id: int,
        created_by: Optional[int] = None
    ) -> Optional[TaxonomyAlias]:
        """
        Crea (o riattiva) alias se non in conflitto.
        Se l'alias coincide col nome canonico target, non crea nulla.
        """
        normalized = self.normalize_name(alias_name)
        if not normalized:
            return None

        # Evita alias identico al nome canonico target
        if entity_type == "label":
            canonical = Label.query.get(canonical_id)
        else:
            canonical = Category.query.get(canonical_id)

        if not canonical:
            return None
        if self.normalize_name(canonical.name) == normalized:
            return None

        # Evita collisioni con canonicali attivi diversi dal target
        conflict = self.find_name_conflict(entity_type, alias_name, exclude_id=canonical_id)
        if conflict:
            return None

        alias = TaxonomyAlias.query.filter_by(
            entity_type=entity_type,
            alias_normalized=normalized
        ).first()

        if alias:
            if alias.canonical_id == canonical_id:
                alias.is_active = True
                alias.alias_name = alias_name
                if created_by:
                    alias.created_by = created_by
                return alias
            return None

        alias = TaxonomyAlias(
            entity_type=entity_type,
            alias_name=alias_name,
            alias_normalized=normalized,
            canonical_id=canonical_id,
            is_active=True,
            created_by=created_by
        )
        self.session.add(alias)
        return alias

    def _create_audit(
        self,
        entity_type: str,
        source_ids: List[int],
        target_id: Optional[int],
        moved_annotations: int,
        dedup_deleted: int,
        mode: str,
        performed_by: Optional[int],
        payload: Optional[Dict] = None
    ) -> TaxonomyMergeAudit:
        audit = TaxonomyMergeAudit(
            entity_type=entity_type,
            source_ids=json.dumps(sorted(set(source_ids or []))),
            target_id=target_id,
            moved_annotations=moved_annotations or 0,
            dedup_deleted=dedup_deleted or 0,
            performed_by=performed_by,
            performed_at=datetime.utcnow(),
            mode=mode,
            payload_json=json.dumps(payload or {}, ensure_ascii=False),
        )
        self.session.add(audit)
        return audit

    def _label_merge_impact(self, source_label_ids: List[int], target_label_id: int) -> Dict:
        all_label_ids = list(set(source_label_ids + [target_label_id]))
        annotations = CellAnnotation.query.filter(CellAnnotation.label_id.in_(all_label_ids)).all()

        moved_annotations = 0
        grouped = defaultdict(int)

        for ann in annotations:
            moved = ann.label_id in source_label_ids
            if moved:
                moved_annotations += 1
                simulated_label_id = target_label_id
            else:
                simulated_label_id = ann.label_id

            key = (
                ann.text_cell_id,
                simulated_label_id,
                ann.user_id,
                ann.status or "active",
            )
            grouped[key] += 1

        dedup_deleted = sum(max(0, count - 1) for count in grouped.values())
        return {
            "moved_annotations": moved_annotations,
            "dedup_deleted": dedup_deleted,
        }

    def dry_run_label_merge(
        self,
        source_label_ids: List[int],
        target_label_id: int,
        performed_by: Optional[int] = None,
        write_audit: bool = False
    ) -> Dict:
        source_label_ids = [int(x) for x in source_label_ids if x is not None]
        target_label_id = int(target_label_id)

        if target_label_id in source_label_ids:
            return {"success": False, "error": "Il target non può essere tra le sorgenti"}
        if not source_label_ids:
            return {"success": False, "error": "Nessuna etichetta sorgente selezionata"}

        target = Label.query.get(target_label_id)
        if not target:
            return {"success": False, "error": "Etichetta target non trovata"}
        if not target.is_active or target.merged_into_label_id is not None:
            return {"success": False, "error": "Etichetta target non valida: deve essere canonica attiva"}

        source_labels = Label.query.filter(Label.id.in_(source_label_ids)).all()
        if len(source_labels) != len(set(source_label_ids)):
            return {"success": False, "error": "Alcune etichette sorgente non esistono"}
        for src in source_labels:
            if src.merged_into_label_id is not None:
                return {"success": False, "error": f'Etichetta sorgente "{src.name}" già deprecata da merge'}

        impact = self._label_merge_impact(source_label_ids, target_label_id)
        payload = {
            "target": {"id": target.id, "name": target.name},
            "sources": [{"id": lbl.id, "name": lbl.name} for lbl in source_labels],
            "impact": impact,
        }

        if write_audit:
            self._create_audit(
                entity_type="label",
                source_ids=source_label_ids,
                target_id=target_label_id,
                moved_annotations=impact["moved_annotations"],
                dedup_deleted=impact["dedup_deleted"],
                mode="dry_run",
                performed_by=performed_by,
                payload=payload,
            )
            self.session.commit()

        return {
            "success": True,
            "target": payload["target"],
            "sources": payload["sources"],
            "moved_annotations": impact["moved_annotations"],
            "dedup_deleted": impact["dedup_deleted"],
            "payload": payload,
        }

    def apply_label_merge(
        self,
        source_label_ids: List[int],
        target_label_id: int,
        performed_by: Optional[int] = None,
        commit: bool = True
    ) -> Dict:
        dry = self.dry_run_label_merge(
            source_label_ids=source_label_ids,
            target_label_id=target_label_id,
            performed_by=performed_by,
            write_audit=False,
        )
        if not dry.get("success"):
            return dry

        source_label_ids = [src["id"] for src in dry["sources"]]

        # Sposta annotazioni
        CellAnnotation.query.filter(
            CellAnnotation.label_id.in_(source_label_ids)
        ).update({"label_id": target_label_id}, synchronize_session=False)

        # Dedup automatico su (text_cell_id, label_id, user_id, status)
        dedup_deleted = 0
        target_annotations = CellAnnotation.query.filter_by(label_id=target_label_id).order_by(CellAnnotation.id.asc()).all()
        seen = {}
        for ann in target_annotations:
            key = (ann.text_cell_id, ann.label_id, ann.user_id, ann.status or "active")
            if key in seen:
                self.session.delete(ann)
                dedup_deleted += 1
            else:
                seen[key] = ann.id

        # Depreca le sorgenti e crea alias verso la canonica
        source_labels = Label.query.filter(Label.id.in_(source_label_ids)).all()
        for src in source_labels:
            src.is_active = False
            src.merged_into_label_id = target_label_id
            self.create_or_activate_alias(
                entity_type="label",
                alias_name=src.name,
                canonical_id=target_label_id,
                created_by=performed_by,
            )

        payload = {
            "target_id": target_label_id,
            "source_ids": source_label_ids,
            "moved_annotations": dry["moved_annotations"],
            "dedup_deleted": dedup_deleted,
        }
        self._create_audit(
            entity_type="label",
            source_ids=source_label_ids,
            target_id=target_label_id,
            moved_annotations=dry["moved_annotations"],
            dedup_deleted=dedup_deleted,
            mode="apply",
            performed_by=performed_by,
            payload=payload,
        )

        if commit:
            self.session.commit()

        return {
            "success": True,
            "target_id": target_label_id,
            "source_ids": source_label_ids,
            "moved_annotations": dry["moved_annotations"],
            "dedup_deleted": dedup_deleted,
        }

    def dry_run_category_merge(
        self,
        source_category_ids: List[int],
        target_category_id: int,
        performed_by: Optional[int] = None,
        write_audit: bool = False
    ) -> Dict:
        source_category_ids = [int(x) for x in source_category_ids if x is not None]
        target_category_id = int(target_category_id)

        if target_category_id in source_category_ids:
            return {"success": False, "error": "Il target non può essere tra le sorgenti"}
        if not source_category_ids:
            return {"success": False, "error": "Nessuna categoria sorgente selezionata"}

        target = Category.query.get(target_category_id)
        if not target:
            return {"success": False, "error": "Categoria target non trovata"}
        if not target.is_active or target.merged_into_category_id is not None:
            return {"success": False, "error": "Categoria target non valida: deve essere canonica attiva"}

        sources = Category.query.filter(Category.id.in_(source_category_ids)).all()
        if len(sources) != len(set(source_category_ids)):
            return {"success": False, "error": "Alcune categorie sorgente non esistono"}
        for src in sources:
            if src.merged_into_category_id is not None:
                return {"success": False, "error": f'Categoria sorgente "{src.name}" già deprecata da merge'}

        moved_labels = Label.query.filter(Label.category_id.in_(source_category_ids)).count()
        payload = {
            "target": {"id": target.id, "name": target.name},
            "sources": [{"id": cat.id, "name": cat.name} for cat in sources],
            "impact": {"moved_labels": moved_labels},
        }

        if write_audit:
            self._create_audit(
                entity_type="category",
                source_ids=source_category_ids,
                target_id=target_category_id,
                moved_annotations=moved_labels,  # compat col campo esistente audit
                dedup_deleted=0,
                mode="dry_run",
                performed_by=performed_by,
                payload=payload,
            )
            self.session.commit()

        return {
            "success": True,
            "target": payload["target"],
            "sources": payload["sources"],
            "moved_labels": moved_labels,
            "payload": payload,
        }

    def apply_category_merge(
        self,
        source_category_ids: List[int],
        target_category_id: int,
        performed_by: Optional[int] = None,
        commit: bool = True
    ) -> Dict:
        dry = self.dry_run_category_merge(
            source_category_ids=source_category_ids,
            target_category_id=target_category_id,
            performed_by=performed_by,
            write_audit=False,
        )
        if not dry.get("success"):
            return dry

        source_category_ids = [src["id"] for src in dry["sources"]]
        target = Category.query.get(target_category_id)

        labels_to_move = Label.query.filter(Label.category_id.in_(source_category_ids)).all()
        for label in labels_to_move:
            label.category_id = target_category_id
            label.category = target.name  # compat legacy

        source_categories = Category.query.filter(Category.id.in_(source_category_ids)).all()
        for src in source_categories:
            src.is_active = False
            src.merged_into_category_id = target_category_id
            self.create_or_activate_alias(
                entity_type="category",
                alias_name=src.name,
                canonical_id=target_category_id,
                created_by=performed_by,
            )

        payload = {
            "target_id": target_category_id,
            "source_ids": source_category_ids,
            "moved_labels": len(labels_to_move),
        }
        self._create_audit(
            entity_type="category",
            source_ids=source_category_ids,
            target_id=target_category_id,
            moved_annotations=len(labels_to_move),
            dedup_deleted=0,
            mode="apply",
            performed_by=performed_by,
            payload=payload,
        )

        if commit:
            self.session.commit()

        return {
            "success": True,
            "target_id": target_category_id,
            "source_ids": source_category_ids,
            "moved_labels": len(labels_to_move),
        }

    def suggest_label_merges(self) -> List[Dict]:
        canonical_labels = self._canonical_labels().all()
        if not canonical_labels:
            return []

        ann_counts = dict(
            db.session.query(CellAnnotation.label_id, db.func.count(CellAnnotation.id))
            .group_by(CellAnnotation.label_id)
            .all()
        )

        groups = defaultdict(list)
        for label in canonical_labels:
            groups[self.normalize_name(label.name)].append(label)

        suggestions = []
        for normalized_key, group in groups.items():
            if len(group) <= 1:
                continue

            ranked = sorted(
                group,
                key=lambda item: (ann_counts.get(item.id, 0), -item.id),
                reverse=True
            )
            target = ranked[0]
            sources = ranked[1:]

            dry = self.dry_run_label_merge(
                source_label_ids=[src.id for src in sources],
                target_label_id=target.id,
                write_audit=False,
            )
            if not dry.get("success"):
                continue

            suggestion = {
                "normalized_key": normalized_key,
                "reason": "Collisione nome normalizzato",
                "score": (len(group) * 10) + dry["moved_annotations"] + (dry["dedup_deleted"] * 5),
                "target": {
                    "id": target.id,
                    "name": target.name,
                    "annotation_count": ann_counts.get(target.id, 0),
                },
                "sources": [
                    {
                        "id": src.id,
                        "name": src.name,
                        "annotation_count": ann_counts.get(src.id, 0),
                    }
                    for src in sources
                ],
                "labels": [
                    {
                        "id": item.id,
                        "name": item.name,
                        "annotation_count": ann_counts.get(item.id, 0),
                    }
                    for item in ranked
                ],
                "impact_preview": {
                    "moved_annotations": dry["moved_annotations"],
                    "dedup_deleted": dry["dedup_deleted"],
                    "source_count": len(sources),
                },
            }
            suggestions.append(suggestion)

        suggestions.sort(key=lambda item: item["score"], reverse=True)
        return suggestions

    def suggest_category_merges(self) -> List[Dict]:
        canonical_categories = self._canonical_categories().all()
        if not canonical_categories:
            return []

        label_counts = dict(
            db.session.query(Label.category_id, db.func.count(Label.id))
            .filter(Label.category_id.isnot(None))
            .group_by(Label.category_id)
            .all()
        )

        groups = defaultdict(list)
        for category in canonical_categories:
            groups[self.normalize_name(category.name)].append(category)

        suggestions = []
        for normalized_key, group in groups.items():
            if len(group) <= 1:
                continue

            ranked = sorted(
                group,
                key=lambda item: (label_counts.get(item.id, 0), -item.id),
                reverse=True
            )
            target = ranked[0]
            sources = ranked[1:]

            moved_labels = sum(label_counts.get(src.id, 0) for src in sources)
            suggestion = {
                "normalized_key": normalized_key,
                "reason": "Collisione nome normalizzato",
                "score": (len(group) * 10) + moved_labels,
                "target": {
                    "id": target.id,
                    "name": target.name,
                    "label_count": label_counts.get(target.id, 0),
                },
                "sources": [
                    {
                        "id": src.id,
                        "name": src.name,
                        "label_count": label_counts.get(src.id, 0),
                    }
                    for src in sources
                ],
                "impact_preview": {
                    "moved_labels": moved_labels,
                    "source_count": len(sources),
                },
            }
            suggestions.append(suggestion)

        suggestions.sort(key=lambda item: item["score"], reverse=True)
        return suggestions

    def dry_run_taxonomy(self, performed_by: Optional[int] = None, write_audit: bool = False) -> Dict:
        label_suggestions = self.suggest_label_merges()
        category_suggestions = self.suggest_category_merges()

        payload = {
            "label_suggestions": label_suggestions,
            "category_suggestions": category_suggestions,
            "summary": {
                "label_candidates": len(label_suggestions),
                "category_candidates": len(category_suggestions),
            },
        }

        if write_audit:
            self._create_audit(
                entity_type="taxonomy",
                source_ids=[],
                target_id=None,
                moved_annotations=0,
                dedup_deleted=0,
                mode="dry_run",
                performed_by=performed_by,
                payload=payload,
            )
            self.session.commit()

        return payload

    def apply_taxonomy_plan(
        self,
        label_merges: List[Dict],
        category_merges: List[Dict],
        performed_by: Optional[int] = None
    ) -> Dict:
        label_results = []
        category_results = []

        for item in label_merges or []:
            source_ids = item.get("source_ids", [])
            target_id = item.get("target_id")
            if not source_ids or target_id is None:
                continue
            result = self.apply_label_merge(
                source_label_ids=[int(x) for x in source_ids],
                target_label_id=int(target_id),
                performed_by=performed_by,
                commit=False,
            )
            if not result.get("success"):
                self.session.rollback()
                return result
            label_results.append(result)

        for item in category_merges or []:
            source_ids = item.get("source_ids", [])
            target_id = item.get("target_id")
            if not source_ids or target_id is None:
                continue
            result = self.apply_category_merge(
                source_category_ids=[int(x) for x in source_ids],
                target_category_id=int(target_id),
                performed_by=performed_by,
                commit=False,
            )
            if not result.get("success"):
                self.session.rollback()
                return result
            category_results.append(result)

        payload = {
            "label_results": label_results,
            "category_results": category_results,
        }
        self._create_audit(
            entity_type="taxonomy",
            source_ids=[],
            target_id=None,
            moved_annotations=sum(x.get("moved_annotations", 0) for x in label_results),
            dedup_deleted=sum(x.get("dedup_deleted", 0) for x in label_results),
            mode="apply",
            performed_by=performed_by,
            payload=payload,
        )
        self.session.commit()

        return {
            "success": True,
            "label_merges_applied": len(label_results),
            "category_merges_applied": len(category_results),
            "label_results": label_results,
            "category_results": category_results,
        }

    def get_recent_audit(self, limit: int = 100) -> List[TaxonomyMergeAudit]:
        return TaxonomyMergeAudit.query.order_by(TaxonomyMergeAudit.performed_at.desc()).limit(limit).all()
