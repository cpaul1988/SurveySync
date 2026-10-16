"""Transactional, idempotent attachment of the legacy engine to a SurveySync job."""
from __future__ import annotations

from pathlib import Path

from surveysync.fieldbook_session import changing_project, path_key


def apply_identity(storage, state, *, adopt: bool = False) -> None:
    context = getattr(storage, 'survey_sync_context', None)
    if not context:
        return
    existing_id = state.surveysync_project_id
    if existing_id and existing_id != context['project_id'] and not adopt:
        raise ValueError('FieldBookSync state belongs to a different SurveySync project; use explicit .fbs import to copy its data.')
    if state.project_name not in {'', 'Untitled Project', context['name']} and not state.legacy_project_name:
        state.legacy_project_name = state.project_name
    state.surveysync_project_id = context['project_id']
    state.project_name = context['name']


def busy(runtime) -> bool:
    thread = getattr(runtime, 'batch_thread', None)
    timer = getattr(runtime, 'live_network_timer', None)
    return (runtime.job.running or runtime.import_job.running
            or bool(thread and thread.is_alive())
            or bool(timer and timer.is_alive())
            or bool(getattr(runtime, 'live_network_rebuild_running', False)))


def describe(runtime) -> dict:
    return {
        'root': str(runtime.storage.root), 'state_path': str(runtime.storage.state_path),
        'job_database': str(runtime.job_store.path), 'ocr_cache': str(runtime.ocr_cache_dir),
        'interpretation_cache': str(runtime.interpretation_cache_dir),
        'project_context': dict(getattr(runtime.storage, 'survey_sync_context', None) or {}),
    }


def rebind(module, storage_root: Path | str, project_context: dict | None = None) -> dict:
    with changing_project():
        old = module.runtime
        with old.lock:
            context = dict(project_context or {})
            same_root = path_key(old.storage.root) == path_key(storage_root)
            old_context = getattr(old.storage, 'survey_sync_context', None) or {}
            if same_root and old_context.get('token') == context.get('token'):
                old.storage.survey_sync_context = context or None
                apply_identity(old.storage, old.storage.state)
                old.storage.save()
                return describe(old)
            if busy(old):
                raise RuntimeError('Cannot switch SurveySync projects while FieldBookSync analysis, import, batch or network work is active.')
            candidate = module.Runtime(storage_root)
            committed = False
            try:
                candidate.storage.survey_sync_context = context or None
                apply_identity(candidate.storage, candidate.storage.state)
                candidate.storage.save()
                # Deferred startup probes are tied to their original runtime. Join
                # before closing its ledger; do not signal application shutdown.
                probe = getattr(old, 'deferred_startup_thread', None)
                if probe and probe.is_alive():
                    probe.join(timeout=2)
                    if probe.is_alive():
                        raise RuntimeError('FieldBookSync startup checks are still finishing. Retry switching projects.')
                candidate_logger = module.configure_logging(candidate.storage.root / 'logs')
                old.job_store.close()
                candidate.shutdown_event = old.shutdown_event  # application lifetime, not project lifetime
                module.runtime = candidate
                module.logger = candidate_logger
                committed = True
                return describe(candidate)
            finally:
                if not committed:
                    candidate.job_store.close()
