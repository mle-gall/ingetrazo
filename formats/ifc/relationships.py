# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared material/style identities and presentation layers for each export."""
from collections import defaultdict
from .step import _s, _f


def ref(node):
    return '#' + str(node)


def refs(nodes):
    return '(' + ','.join(map(ref, nodes)) + ')'


class Appearance:
    def __init__(self, scene, writer, relation):
        self.scene, self.w, self.relation = scene, writer, relation
        self.materials, self.styles = {}, {}
        self.layers = defaultdict(set)

    def material(self, name):
        if name not in self.materials:
            self.materials[name] = self.w.entity('IfcMaterial', Name=_s(name))
        return self.materials[name]

    def apply(self, record, group, faces, node, guid, representation, item):
        w = self.w
        areas = defaultdict(float)
        for face in faces:
            if face.attrs.get('mat'):
                areas[face.attrs['mat']] += face.area()
        paint = getattr(group, 'material', None) or {}
        material = record.get('material') or (max(areas, key=areas.get) if areas else None) or paint.get('mat')
        name = material.get('name', '') if isinstance(material, dict) else material
        if name:
            mat = self.material(name)
            if isinstance(material, dict) and material.get('layers'):
                key = (name, tuple((layer['name'], layer['thickness']) for layer in material['layers']))
                if key not in self.materials:
                    layers = [w.entity('IfcMaterialLayer', Material=ref(self.material(layer['name'])),
                                       LayerThickness=_f(layer['thickness'])) for layer in material['layers']]
                    self.materials[key] = w.entity('IfcMaterialLayerSet', MaterialLayers=refs(layers), LayerSetName=_s(name))
                mat = self.materials[key]
            self.relation('IfcRelAssociatesMaterial', (guid, 'material'), RelatedObjects=refs([node]), RelatingMaterial=ref(mat))
        recipe = self.scene.materials.get(name)
        color = getattr(recipe, 'color', None)
        opacity = getattr(recipe, 'opacity', None)
        if color is None:
            source = next((f.attrs for f in faces if f.attrs.get('mat') == name and f.attrs.get('color')), paint)
            color, opacity = source.get('color'), source.get('opacity')
        if color is not None and item is not None:
            alpha = opacity if opacity is not None else color[3] if len(color) > 3 else 1.
            key = (name, tuple(color[:3]), alpha)
            if key not in self.styles:
                rgb = w.entity('IfcColourRgb', Red=_f(color[0]), Green=_f(color[1]), Blue=_f(color[2]))
                render = w.entity('IfcSurfaceStyleRendering', SurfaceColour=ref(rgb), Transparency=_f(1-alpha), ReflectanceMethod='.NOTDEFINED.')
                self.styles[key] = w.entity('IfcSurfaceStyle', Name=_s(name or 'Colour'), Side='.BOTH.', Styles=refs([render]))
            w.entity('IfcStyledItem', Item=ref(item), Styles=refs([self.styles[key]]))
        if representation is not None:
            from core.layers import DEFAULT_LAYER
            names = {f.attrs.get('layer') or getattr(group, 'layer', None) or DEFAULT_LAYER for f in faces}
            if group is not None:
                names.add(group.layer or DEFAULT_LAYER)
            for layer in self.scene.layers:
                if layer.name in names:
                    self.layers[(layer.name, layer.uid)].add(representation)

    def finish(self):
        for (name, uid), representations in self.layers.items():
            self.w.entity('IfcPresentationLayerAssignment', Name=_s(name), Identifier=_s(uid), AssignedItems=refs(sorted(representations)))
