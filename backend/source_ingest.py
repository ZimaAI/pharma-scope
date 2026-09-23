"""Immutable snapshots, evidence and monotonically ordered source observations.

The caller holds the repository workspace transaction while applying a batch;
operation_key identifies a source record within one durable sync attempt.
"""
from __future__ import annotations
import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any
from .sources import SourceError, SourceEnvelope, date_value


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _diff(before: Any, after: Any, path: str = '') -> list[dict[str, Any]]:
    changes = []
    if isinstance(before, dict) and isinstance(after, dict):
        for key in sorted(set(before) | set(after)):
            pointer = path + '/' + key.replace('~', '~0').replace('/', '~1')
            if key not in before or key not in after:
                changes.append({'path': pointer, 'type': 'added' if key not in before else 'removed', 'before': before.get(key), 'after': after.get(key)})
            else:
                changes.extend(_diff(before[key], after[key], pointer))
    elif before != after:
        changes.append({'path': path or '/', 'type': 'changed', 'before': before, 'after': after})
    return changes


class SnapshotIngestor:
    def __init__(self, state: Any):
        self.state = state

    def _evidence(self, snapshot: dict[str, Any]) -> list[str]:
        if not hasattr(self.state, 'evidence'):
            self.state.evidence = {}
        existing = [e['id'] for e in self.state.evidence.values() if e.get('workspace_id') == snapshot['workspace_id'] and e.get('snapshot_id') == snapshot['id']]
        if existing:
            return existing
        # Evidence is extracted deterministically from immutable normalized
        # fields. Models cannot create snippets or alter their locators.
        candidates = [('/normalized', _json(snapshot['normalized']))]
        if len(candidates[0][1]) > 20000:
            candidates = [('/normalized/' + key.replace('~', '~0').replace('/', '~1'), value if isinstance(value, str) else _json(value)) for key, value in snapshot['normalized'].items() if value is not None]
        ids = []
        for path, text in candidates:
            if not text:
                continue
            locator = {'kind': 'json_pointer', 'path': path}
            if len(text) > 20000:
                locator = {'kind': 'text_range', 'section': path, 'start': 0, 'end': 20000}
                text = text[:20000]
            eid = str(uuid.uuid4())
            self.state.evidence[eid] = {'id': eid, 'workspace_id': snapshot['workspace_id'], 'created_at': snapshot['first_observed_at'],
                'snapshot_id': snapshot['id'], 'locator': locator, 'quoted_text': text, 'snippet_hash': hashlib.sha256(text.encode()).hexdigest(),
                'original_language': 'en', 'translation_text': None, 'extractor_version': 'pharma-normalized-v1'}
            ids.append(eid)
        return ids

    def ingest(self, workspace_id: str, envelope: SourceEnvelope, *, operation_key: str, kind: str | None = None) -> dict[str, Any]:
        record = next((r for r in self.state.records.values() if r.get('workspace_id') == workspace_id and r.get('source') == envelope.source and r.get('external_id') == envelope.external_id), None)
        if record is None:
            record = {'id': str(uuid.uuid4()), 'workspace_id': workspace_id, 'created_at': envelope.fetched_at, 'source': envelope.source,
                      'external_id': envelope.external_id, 'kind': kind or ('trial' if envelope.source == 'ctgov' else 'publication'),
                      'canonical_url': self._url(envelope.source, envelope.external_id), 'current_snapshot_id': None, 'current_observation_id': None,
                      'updated_at': envelope.fetched_at, 'is_demo': False, 'current_projection': envelope.normalized}
            self.state.records[record['id']] = record
        prior = sorted((o for o in self.state.observations.values() if o.get('workspace_id') == workspace_id and o.get('record_id') == record['id']), key=lambda o: int(o.get('observation_seq', 0)))
        prior_operation = next((o for o in prior if o.get('operation_key') == operation_key), None)
        if prior_operation:
            return prior_operation
        prior_success = next((o for o in reversed(prior) if o.get('outcome') != 'failed' and o.get('snapshot_id')), None)
        prior_snapshot = self.state.snapshots.get(prior_success['snapshot_id']) if prior_success else None
        snapshot = next((s for s in self.state.snapshots.values() if s.get('workspace_id') == workspace_id and s.get('record_id') == record['id'] and s.get('content_hash') == envelope.content_hash and s.get('normalizer_version') == 'v1'), None)
        if snapshot is None:
            snapshot = {'id': str(uuid.uuid4()), 'workspace_id': workspace_id, 'record_id': record['id'], 'content_hash': envelope.content_hash,
                        'normalizer_version': 'v1', 'raw_payload': envelope.raw_payload if isinstance(envelope.raw_payload, dict) else {'content': envelope.raw_payload},
                        'normalized': envelope.normalized, 'source_updated': date_value(envelope.source_updated),
                        'first_observed_at': envelope.fetched_at, 'is_demo': False, 'created_at': envelope.fetched_at}
            self.state.snapshots[snapshot['id']] = snapshot
        ids = self._evidence(snapshot)
        outcome = 'baseline' if prior_snapshot is None else 'unchanged' if prior_snapshot['id'] == snapshot['id'] else 'changed'
        obs = {'id': str(uuid.uuid4()), 'workspace_id': workspace_id, 'record_id': record['id'], 'snapshot_id': snapshot['id'],
               'observation_seq': max((int(o.get('observation_seq', 0)) for o in prior), default=0) + 1, 'fetched_at': envelope.fetched_at,
               'outcome': outcome, 'error_code': None, 'operation_key': operation_key, 'created_at': envelope.fetched_at}
        envelope.observation_seq = obs['observation_seq']
        self.state.observations[obs['id']] = obs
        record.update(current_snapshot_id=snapshot['id'], current_observation_id=obs['id'], current_projection=envelope.normalized, updated_at=envelope.fetched_at)
        changes = _diff((prior_snapshot or {}).get('normalized', {}), envelope.normalized) if prior_snapshot else []
        if outcome == 'changed' and changes:
            if not hasattr(self.state, 'events'):
                self.state.events = {}
            if not hasattr(self.state, 'revisions'):
                self.state.revisions = {}
            event = next((e for e in self.state.events.values() if e.get('workspace_id') == workspace_id and e.get('record_id') == record['id'] and e.get('category') == 'source_change'), None)
            if event is None:
                event = {'id': str(uuid.uuid4()), 'workspace_id': workspace_id, 'record_id': record['id'], 'category': 'source_change',
                         'title': f'{record["source"]} record changed', 'latest_revision_id': None, 'updated_at': envelope.fetched_at, 'created_at': envelope.fetched_at}
                self.state.events[event['id']] = event
            revisions = [r for r in self.state.revisions.values() if r.get('workspace_id') == workspace_id and r.get('event_id') == event['id']]
            prior_ids = self._evidence(prior_snapshot)
            revision = {'id': str(uuid.uuid4()), 'workspace_id': workspace_id, 'event_id': event['id'], 'revision_no': max((int(r['revision_no']) for r in revisions), default=0) + 1,
                        'before_observation_id': prior_success['id'], 'after_observation_id': obs['id'], 'changes': changes,
                        'evidence_ids': list(dict.fromkeys(prior_ids + ids)), 'severity': 'info', 'observed_at': envelope.fetched_at, 'created_at': envelope.fetched_at}
            self.state.revisions[revision['id']] = revision
            event.update(latest_revision_id=revision['id'], updated_at=envelope.fetched_at)
        return obs

    def record_failure(self, workspace_id: str, *, source: str, external_id: str, operation_key: str, error: SourceError) -> dict[str, Any]:
        record = next((r for r in self.state.records.values() if r.get('workspace_id') == workspace_id and r.get('source') == source and r.get('external_id') == external_id), None)
        if record is None:
            record = {'id': str(uuid.uuid4()), 'workspace_id': workspace_id, 'created_at': _now(), 'source': source, 'external_id': external_id,
                      'kind': 'trial' if source == 'ctgov' else 'publication', 'canonical_url': self._url(source, external_id),
                      'current_snapshot_id': None, 'current_observation_id': None, 'updated_at': _now(), 'is_demo': False, 'current_projection': {}}
            self.state.records[record['id']] = record
        prior = [o for o in self.state.observations.values() if o.get('workspace_id') == workspace_id and o.get('record_id') == record['id']]
        existing = next((o for o in prior if o.get('operation_key') == operation_key), None)
        if existing:
            return existing
        timestamp = _now()
        obs = {'id': str(uuid.uuid4()), 'workspace_id': workspace_id, 'record_id': record['id'], 'snapshot_id': record.get('current_snapshot_id'),
               'observation_seq': max((int(o.get('observation_seq', 0)) for o in prior), default=0) + 1, 'fetched_at': timestamp,
               'outcome': 'failed', 'error_code': error.code, 'operation_key': operation_key, 'created_at': timestamp}
        self.state.observations[obs['id']] = obs
        return obs

    @staticmethod
    def _url(source: str, external_id: str) -> str:
        return f'https://clinicaltrials.gov/study/{external_id}' if source == 'ctgov' else f'https://pubmed.ncbi.nlm.nih.gov/{external_id}/'
