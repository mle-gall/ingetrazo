# SPDX-License-Identifier: GPL-3.0-or-later
"""Optional independent oracle for the hand-written interoperability facts."""
import pytest
from core.ifc_tables import TABLES

@pytest.mark.parametrize('schema', ['IFC4', 'IFC4X3_ADD2'])
def test_predefined_facts_match_schema(schema):
    ifc = pytest.importorskip('ifcopenshell.ifcopenshell_wrapper')
    oracle = ifc.schema_by_name(schema)
    differences = []
    for name, fact in TABLES.items():
        if schema not in fact['schemas']:
            continue
        entity = oracle.declaration_by_name(name)
        attr = next((a for a in entity.all_attributes() if a.name() == 'PredefinedType'), None)
        expected = list(attr.type_of_attribute().declared_type().enumeration_items()) if attr else []
        if set(expected) != set(fact['predefined_types'][schema]):
            differences.append((name, expected))
    assert not differences, '\n'.join(name + ': ' + ' '.join(values) for name, values in differences)


def test_common_property_names_match_schema():
    psets = pytest.importorskip('ifcopenshell.util.pset')
    template = psets.get_template('IFC4')
    differences = []
    for name, fact in TABLES.items():
        common = template.get_by_name('Pset_' + name[3:] + 'Common')
        expected = {p.Name: p for p in common.HasPropertyTemplates} if common else {}
        # The bundled IFC4 pset fixture mislabels LoadBearing with its description.
        bad = 'Indicates whether the object is intended to carry loads (TRUE) or not (FALSE).'
        if bad in expected:
            expected['LoadBearing'] = expected.pop(bad)
        if set(expected) != set(fact['common']):
            props = []
            for key, p in expected.items():
                enum = getattr(p, 'Enumerators', None)
                values = [v.wrappedValue for v in enum.EnumerationValues] if enum else []
                props.append(key + ':' + str(p.PrimaryMeasureType) + (':' + ','.join(values) if values else ''))
            differences.append(name + ' ' + ' '.join(props))
    assert not differences, '\n'.join(differences)
