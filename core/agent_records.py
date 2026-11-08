# SPDX-License-Identifier: GPL-3.0-or-later
"""Record tools keep metadata edits atomic without copying model geometry."""
from collections import Counter
from copy import deepcopy

from core import record, bim_registry
from core.agent_tools import json_value
from core.history import SetRecordCommand, SetRegistryCommand, CompoundCommand
from core.ifc_tables import IFC_CLASSES, TABLES, SCHEMAS, STATUS, common_pset, predefined_types


def page(rows, offset, limit):
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError('offset must be nonnegative and limit between 1 and 1000')
    return dict(rows=rows[offset:offset + limit], total=len(rows),
                next_offset=offset + limit if offset + limit < len(rows) else None)


def schema_name(schema):
    if schema not in SCHEMAS:
        raise ValueError('Unsupported schema: ' + str(schema))


class RecordTools:
    def _tool_query_registry(self):
        return json_value(bim_registry.get(self._viewport.scene))

    def _record_view(self, group, registry, schema):
        try:
            view = record.describe(group)
        except (TypeError, AttributeError):
            # Forced invalid classes may not support the role lookup.
            view = dict(uid=group.uid, name=group.name,
                        record=record.normalize(group.ifc), role=None)
        value = view['record']
        view['problems'] = record.validate(value, registry, schema) if value else []
        try:
            view['resolved'] = record.apply_type(value, registry) if value else None
        except (TypeError, AttributeError, ValueError):
            # The validator reports malformed type/pset fields; keep them readable.
            view['resolved'] = None
        return json_value(view)

    def _tool_query_record(self, uid, schema='IFC4'):
        schema_name(schema)
        return self._record_view(self._find(uid)[0], self._tool_query_registry(), schema)

    def _tool_query_records(self, system=None, classification_system=None, code=None,
                            type=None, untagged=False, name=None, offset=0, limit=200,
                            schema='IFC4', **filters):
        schema_name(schema)
        cls = filters.pop('class', None)
        if filters:
            raise ValueError('Unknown filters: ' + ', '.join(filters))
        registry = self._tool_query_registry()
        rows, counts, tagged, untagged_count = [], Counter(), 0, 0
        for group, parents, _ in self._groups():
            value = group.ifc or {}
            if value:
                tagged += 1
                counts[str(value.get('class'))] += 1
            else:
                untagged_count += 1
            if untagged and value:
                continue
            if cls is not None and value.get('class') != cls:
                continue
            if type is not None and value.get('type') != type:
                continue
            if system is not None and system not in value.get('systems', []):
                continue
            if name is not None and name.casefold() not in (group.name or '').casefold():
                continue
            classifications = value.get('classifications', [])
            if (classification_system is not None or code is not None) and not any(
                    (classification_system is None or c.get('system') == classification_system)
                    and (code is None or c.get('code') == code) for c in classifications):
                continue
            rows.append(dict(uid=group.uid, name=group.name, path=[p.name for p in parents],
                **{k: value.get(k) for k in ('class', 'predefined_type', 'tag', 'type')},
                classifications=classifications, systems=value.get('systems', []),
                problems=len(record.validate(value, registry, schema)) if value else 0))
        return json_value(dict(**page(rows, offset, limit),
            totals=dict(tagged=tagged, untagged=untagged_count, by_class=dict(counts))))

    def _tool_query_vocabulary(self, schema='IFC4', classification_system=None,
                               search=None, offset=0, limit=200, **filters):
        schema_name(schema)
        cls = filters.pop('class', None)
        if filters:
            raise ValueError('Unknown filters: ' + ', '.join(filters))
        classes = [c for c in IFC_CLASSES if schema in TABLES[c]['schemas']]
        if cls is not None:
            if cls not in classes:
                raise ValueError('Class is not supported in ' + schema)
            classes = [cls]
        systems = self._tool_query_registry()['classification_systems']
        if classification_system is not None and classification_system not in systems:
            raise ValueError('Unknown classification system')
        summaries, codes = {}, []
        for key, value in systems.items():
            summaries[key] = {k: v for k, v in value.items() if k != 'codes'}
            summaries[key]['code_count'] = len(value.get('codes', {}))
            if classification_system is not None and key != classification_system:
                continue
            if classification_system is None and search is None:
                continue
            for code, entry in value.get('codes', {}).items():
                if search is None or search.casefold() in (code + ' ' + entry['name']).casefold():
                    codes.append(dict(system=key, code=code, **entry))
        return json_value(dict(schema=schema, classes=[dict(
            **{'class': c}, role=record.role({'class': c}),
            predefined_types=predefined_types(c, schema),
            common_pset=common_pset(c), properties=TABLES[c]['common']) for c in classes],
            status=STATUS, classification_systems=summaries, codes=page(codes, offset, limit)))

    def _record_targets(self, uids):
        if not isinstance(uids, list) or any(not isinstance(uid, str) for uid in uids):
            raise ValueError('uids must be a list of strings')
        lookup = {g.uid: g for g, _, _ in self._groups()}
        missing = [uid for uid in uids if uid not in lookup]
        if missing:
            raise ValueError('Unknown group uids: ' + ', '.join(missing))
        return [lookup[uid] for uid in dict.fromkeys(uids)]

    def _edit_records(self, targets, patches, schema, force):
        schema_name(schema)
        registry = self._tool_query_registry()
        problems = {}
        for group, patch in zip(targets, patches):
            patch = json_value(patch)
            if patch is not None and not isinstance(patch, dict):
                raise ValueError('patch must be an object or null')
            value = None if patch is None else {**deepcopy(group.ifc or {}), **patch}
            if value is not None:
                # Match the command: a caller cannot replace the identity.
                value.pop('guid', None)
                if group.ifc and group.ifc.get('guid'):
                    value['guid'] = group.ifc['guid']
            problems[group.uid] = record.validate(value, registry, schema) if value is not None else []
        if any(problems.values()) and not force:
            return json_value(dict(applied=False, problems=problems, records=[
                self._record_view(g, registry, schema) for g in targets]))
        if targets:
            if all(patch == patches[0] for patch in patches):
                command = SetRecordCommand(targets, patches[0])
            else:
                command = CompoundCommand(SetRecordCommand([g], patch)
                    for g, patch in zip(targets, patches))
            self._viewport.history.execute(command)
        return json_value(dict(applied=True, problems=problems, records=[
            self._record_view(g, registry, schema) for g in targets]))

    def _tool_set_record(self, uids, patch, validate_schema='IFC4', force=False):
        targets = self._record_targets(uids)
        return self._edit_records(targets, [patch] * len(targets), validate_schema, force)

    def _tool_tag(self, uids, ifc_class, name=None):
        patch = {'class': ifc_class}
        if name is not None:
            patch['name'] = name
        return self._tool_set_record(uids, patch)

    def _tool_untag(self, uids):
        return self._tool_set_record(uids, None)

    def _tool_add_classification(self, uids, system, code, name=None):
        targets = self._record_targets(uids)
        registry = self._tool_query_registry()
        if system not in registry['classification_systems']:
            raise ValueError('Unknown classification system')
        if name is None:
            name = registry['classification_systems'][system].get('codes', {}).get(code, {}).get('name', code)
        patches = []
        for group in targets:
            items = [c for c in (group.ifc or {}).get('classifications', [])
                     if (c['system'], c['code']) != (system, code)]
            patches.append({'classifications': items + [dict(system=system, code=code, name=name)]})
        return self._edit_records(targets, patches, 'IFC4', False)

    def _tool_remove_classification(self, uids, system, code=None):
        targets = self._record_targets(uids)
        patches = [dict(classifications=[c for c in (g.ifc or {}).get('classifications', [])
                   if not (c['system'] == system and (code is None or c['code'] == code))]) for g in targets]
        return self._edit_records(targets, patches, 'IFC4', False)

    def _tool_set_registry(self, value):
        value = json_value(value)
        self._viewport.history.execute(SetRegistryCommand(value))
        return self._tool_query_registry()

    def _registry_upsert(self, section, key, value):
        if not isinstance(key, str) or not key:
            raise ValueError('Registry key must be nonempty text')
        registry = self._tool_query_registry()
        registry.setdefault(section, {})[key] = value
        return self._tool_set_registry(registry)

    def _tool_add_classification_system(self, key, name, edition='', source='', description='', codes=None):
        return self._registry_upsert('classification_systems', key, dict(
            name=name, edition=edition, source=source, description=description, codes=codes or {}))

    def _tool_import_classification_codes(self, system, csv_text):
        return self._tool_set_registry(bim_registry.import_codes_csv(self._tool_query_registry(), system, csv_text))

    def _tool_set_type(self, key, value):
        return self._registry_upsert('types', key, value)

    def _tool_set_system(self, key, value):
        return self._registry_upsert('systems', key, value)

    def _registry_delete(self, section, key, force):
        registry = self._tool_query_registry()
        if key not in registry.get(section, {}):
            raise ValueError('Unknown registry key: ' + key)
        referenced = []
        for group, _, _ in self._groups():
            value = record.apply_type(group.ifc, registry) if group.ifc else {}
            used = (value.get('type') == key if section == 'types' else
                    key in value.get('systems', []) if section == 'systems' else
                    any(c.get('system') == key for c in value.get('classifications', [])))
            if used:
                referenced.append(group.uid)
        if referenced and not force:
            return json_value(dict(applied=False, uids=referenced))
        del registry[section][key]
        result = self._tool_set_registry(registry)
        return json_value(dict(applied=True, uids=referenced, registry=result))

    def _tool_delete_type(self, key, force=False):
        return self._registry_delete('types', key, force)

    def _tool_delete_system(self, key, force=False):
        return self._registry_delete('systems', key, force)

    def _tool_delete_classification_system(self, key, force=False):
        return self._registry_delete('classification_systems', key, force)
