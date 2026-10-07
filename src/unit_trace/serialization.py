"""Explicit bundle export and untrusted snapshot import with profile comparison."""

import hashlib
import json
import re

from .models import EvaluationReport, LoadedProject, Profile, Project, input_error
from .profile import get_profile
from .validation import load_json, parse_project

BUNDLE_BYTES = 8388608


def _json_bytes(data: object) -> bytes:
    try:
        return json.dumps(data, sort_keys=True, ensure_ascii=False,
                          separators=(',', ':'), allow_nan=False).encode('utf-8')
    except (TypeError, ValueError, UnicodeError, RecursionError, OverflowError):
        raise input_error('invalid_schema', '$', 'Expected bounded JSON-compatible data.') from None


def canonical_project_bytes(project: Project) -> bytes:
    """UTF-8, sorted object keys, compact separators, original NumberText/array order."""
    return _json_bytes(project.to_json())


def project_hash(project: Project) -> str:
    return hashlib.sha256(canonical_project_bytes(project)).hexdigest()


def serialize_bundle(project: Project, report: EvaluationReport) -> bytes:
    parse_project(project.to_json())
    if report.schema_version != 1 or report.project_hash != project_hash(project):
        raise input_error('invalid_schema', 'report.projectHash', 'Report does not match the current project.')
    if report.profile != get_profile():
        raise input_error('engine_mismatch', 'report.profile', 'Report requires the current engine profile.')
    raw = _json_bytes({'schemaVersion': 1, 'project': project.to_json(), 'report': report.to_json()})
    if len(raw) > BUNDLE_BYTES:
        raise input_error('limit_exceeded', '$', 'Bundle exceeds 8 MiB.')
    return raw


def _profile(data: object) -> Profile:
    fields = {'id', 'schemaVersion', 'pythonVersion', 'pintVersion', 'dependencies',
              'unitWhitelistVersion', 'definitionHashes'}
    if not isinstance(data, dict) or set(data) != fields:
        raise input_error('invalid_schema', 'report.profile', 'Missing or unknown engine profile fields.')
    if data['id'] != 'unit-trace-scalar-v1' or type(data['schemaVersion']) is not int or data['schemaVersion'] != 1:
        raise input_error('invalid_schema', 'report.profile', 'Unsupported engine profile or schema.')
    for key in ('pythonVersion', 'pintVersion'):
        if not isinstance(data[key], str) or not 1 <= len(data[key]) <= 128:
            raise input_error('invalid_schema', 'report.profile.' + key, 'Invalid engine version text.')
    if type(data['unitWhitelistVersion']) is not int or not 1 <= data['unitWhitelistVersion'] <= 2147483647:
        raise input_error('invalid_schema', 'report.profile.unitWhitelistVersion', 'Invalid whitelist version.')
    for key in ('dependencies', 'definitionHashes'):
        mapping = data[key]
        if not isinstance(mapping, dict) or len(mapping) > 32:
            raise input_error('invalid_schema', 'report.profile.' + key, 'Invalid profile mapping.')
        for name, value in mapping.items():
            if not isinstance(name, str) or not 1 <= len(name) <= 128 or not isinstance(value, str) or not 1 <= len(value) <= 128:
                raise input_error('invalid_schema', 'report.profile.' + key, 'Invalid profile mapping entry.')
            if key == 'definitionHashes' and re.fullmatch('[0-9a-f]{64}', value) is None:
                raise input_error('invalid_schema', 'report.profile.definitionHashes', 'Expected SHA256 resource hashes.')
    return Profile(data['id'], data['schemaVersion'], data['pythonVersion'], data['pintVersion'],
                   dict(data['dependencies']), data['unitWhitelistVersion'], dict(data['definitionHashes']))


def parse_bundle(data: object) -> LoadedProject:
    # The caller may supply decoded data, so do not rely on an earlier byte/depth guard.
    data = load_json(_json_bytes(data), max_bytes=BUNDLE_BYTES)
    if isinstance(data, dict) and 'project' in data:
        if set(data) != {'schemaVersion', 'project', 'report'} or type(data['schemaVersion']) is not int or data['schemaVersion'] != 1:
            raise input_error('invalid_schema', '$', 'Unsupported bundle schema or fields.')
        report = data['report']
        if not isinstance(report, dict) or 'profile' not in report:
            raise input_error('invalid_schema', 'report', 'Expected a snapshot with an engine profile.')
        source = _profile(report['profile'])
        # Never deserialize quantities/errors/traces into computation state.
        return LoadedProject(parse_project(data['project']), source, source != get_profile())
    return LoadedProject(parse_project(data), None, False)
