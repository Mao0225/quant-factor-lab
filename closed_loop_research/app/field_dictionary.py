"""Display-only annotations from the supplied source dictionary, never data approval."""
import copy
import hashlib
import re
from functools import lru_cache
from pathlib import Path


DEFAULT_DICTIONARY = Path(__file__).parent / 'resources' / '日K表字段说明.md'


@lru_cache(maxsize=8)
def _parse_document(content, filename):
    fingerprint = hashlib.sha256(content).hexdigest()
    entries, section = {}, ''
    for number, line in enumerate(content.decode('utf-8-sig').splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith('#'):
            section = stripped.lstrip('#').strip()
        if not stripped.startswith('|') or not stripped.endswith('|'):
            continue
        cells = [v.strip().replace(r'\|', '|') for v in re.split(r'(?<!\\)\|', stripped)[1:-1]]
        if len(cells) != 3:
            continue
        name = cells[0].strip('`')
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name):
            continue
        if name in entries:
            raise ValueError(f'duplicate field dictionary entry: {name} (line {number})')
        entries[name] = dict(description=cells[1], source_notes=cells[2], description_status='matched',
                             documentation=dict(file=filename, sha256=fingerprint, line=number, section=section))
    return entries, fingerprint


def enrich_catalog(fields, dictionary_path=DEFAULT_DICTIONARY):
    """Match exact source column names, preserving every computational/quality flag."""
    path = Path(dictionary_path)
    entries, fingerprint = _parse_document(path.read_bytes(), path.name)
    output, matched, missing = copy.deepcopy(fields), [], []
    for field in output:
        name = field['name']
        if name in entries:
            field.update(copy.deepcopy(entries[name]))
            matched.append(name)
        else:
            field.update(description=field.get('description') or '提供的字段说明文档未收录此字段',
                         source_notes='', description_status='unmatched', documentation=None)
            missing.append(name)
    summary = dict(file=path.name, sha256=fingerprint, document_fields=len(entries),
                   catalog_fields=len(output), matched=len(matched), unmatched_fields=missing,
                   unused_document_fields=sorted(set(entries)-{f['name'] for f in output}),
                   matching='exact_source_field_name',
                   note='中文说明与备注来自字段文档，不代表数据时点、单位或历史值已核验；不改变训练及过滤权限。')
    return output, summary
