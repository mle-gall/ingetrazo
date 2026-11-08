# SPDX-License-Identifier: GPL-3.0-or-later
"""Attribute order is explicit so schema drift fails before a file is written.

These are generated interoperability facts, not bundled EXPRESS definitions.
"""
from .step import _Writer

from core.ifc_tables_data import SCHEMA_DATA

ORDERS = SCHEMA_DATA['IFC4']['orders']

class Builder(_Writer):
    def __init__(self, schema):
        super().__init__()
        self.schema = schema

    def attributes(self, entity):
        return SCHEMA_DATA[self.schema]['orders'][entity.upper()]

    def add(self, entity, *attrs):
        if len(attrs) != len(self.attributes(entity)):
            raise ValueError('Wrong attribute count for ' + entity)
        return super().add(entity.upper(), *attrs)

    def entity(self, entity, **values):
        attrs = self.attributes(entity)
        # Required enum attributes can honestly express an unspecified value.
        for name, enum in SCHEMA_DATA[self.schema]['enums'][entity.upper()].items():
            if enum['required'] and name not in values and 'NOTDEFINED' in enum['members']:
                values[name] = '.NOTDEFINED.'
        if entity == 'IfcStructuralLoadCase':
            values['PredefinedType'] = '.LOAD_CASE.'
        if entity == 'IfcStructuralResultGroup':
            values.setdefault('IsLinear', '.F.')
        unknown = values.keys() - set(attrs)
        if unknown:
            raise ValueError(f'{entity}: unknown attributes {unknown}')
        return self.add(entity, *(values.get(key, '$') for key in attrs))
