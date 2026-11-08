# SPDX-License-Identifier: GPL-3.0-or-later
"""Hand-written interoperability facts; no redistributed EXPRESS or XML.

References: buildingSMART IFC4 ADD2 TC1 and IFC4.3 ADD2 lexical documentation.
An empty enumeration means the entity has no PredefinedType attribute.
Common templates are a curated editable subset, not a schema validator.
"""
SCHEMAS = ('IFC4', 'IFC4X3_ADD2')
STATUS = 'NEW EXISTING DEMOLISH TEMPORARY OTHER NOTKNOWN UNSET'.split()
_ENUMS = {
    'Wall': 'MOVABLE PARAPET PARTITION PLUMBINGWALL SHEAR SOLIDWALL STANDARD POLYGONAL ELEMENTEDWALL',
    'Slab': 'FLOOR ROOF LANDING BASESLAB',
    'Column': 'COLUMN PILASTER', 'Beam': 'BEAM JOIST HOLLOWCORE LINTEL SPANDREL T_BEAM',
    'Footing': 'CAISSON_FOUNDATION FOOTING_BEAM PAD_FOOTING PILE_CAP STRIP_FOOTING',
    'Roof': 'FLAT_ROOF SHED_ROOF GABLE_ROOF HIP_ROOF HIPPED_GABLE_ROOF GAMBREL_ROOF MANSARD_ROOF BARREL_ROOF RAINBOW_ROOF BUTTERFLY_ROOF PAVILION_ROOF DOME_ROOF FREEFORM',
    'Stair': 'STRAIGHT_RUN_STAIR TWO_STRAIGHT_RUN_STAIR QUARTER_WINDING_STAIR QUARTER_TURN_STAIR HALF_WINDING_STAIR HALF_TURN_STAIR TWO_QUARTER_WINDING_STAIR TWO_QUARTER_TURN_STAIR THREE_QUARTER_WINDING_STAIR THREE_QUARTER_TURN_STAIR SPIRAL_STAIR DOUBLE_RETURN_STAIR CURVED_RUN_STAIR TWO_CURVED_RUN_STAIR',
    'Ramp': 'STRAIGHT_RUN_RAMP TWO_STRAIGHT_RUN_RAMP QUARTER_TURN_RAMP TWO_QUARTER_TURN_RAMP HALF_TURN_RAMP SPIRAL_RAMP',
    'Door': 'DOOR GATE TRAPDOOR', 'Window': 'WINDOW SKYLIGHT LIGHTDOME',
    'Railing': 'HANDRAIL GUARDRAIL BALUSTRADE',
    'Covering': 'CEILING FLOORING CLADDING ROOFING MOLDING SKIRTING INSULATION MEMBRANE SLEEVING WRAPPING',
    'Pile': 'BORED DRIVEN JETGROUTING COHESION FRICTION SUPPORT',
    'Member': 'BRACE CHORD COLLAR MEMBER MULLION PLATE POST PURLIN RAFTER STRINGER STRUT STUD',
    'Space': 'SPACE PARKING GFA INTERNAL EXTERNAL',
    'ReinforcingBar': 'ANCHORING EDGE LIGATURE MAIN PUNCHING RING SHEAR STUD',
    'BuildingElementProxy': 'COMPLEX ELEMENT PARTIAL PROVISIONFORVOID PROVISIONFORSPACE',
    'ElementAssembly': 'ACCESSORY_ASSEMBLY ARCH BEAM_GRID BRACED_FRAME GIRDER REINFORCEMENT_UNIT RIGID_FRAME SLAB_FIELD TRUSS',
    'BuildingElementPart': 'INSULATION PRECASTPANEL', 'CurtainWall': '',
    'Plate': 'CURTAIN_PANEL SHEET', 'FurnishingElement': None,
    'TransportElement': 'ELEVATOR ESCALATOR MOVINGWALKWAY CRANEWAY LIFTINGGEAR',
    'GeographicElement': 'TERRAIN',
    'DiscreteAccessory': 'ANCHORPLATE BRACKET SHOE',
    'MechanicalFastener': 'ANCHORBOLT BOLT DOWEL NAIL NAILPLATE RIVET SCREW SHEARCONNECTOR STAPLE STUDSHEARCONNECTOR',
    'Fastener': 'GLUE MORTAR WELD',
    'FlowSegment': None, 'FlowFitting': None, 'FlowTerminal': None,
    'PipeSegment': 'CULVERT FLEXIBLESEGMENT RIGIDSEGMENT GUTTER SPOOL',
    'DuctSegment': 'RIGIDSEGMENT FLEXIBLESEGMENT',
    'CableCarrierSegment': 'CABLELADDERSEGMENT CABLETRAYSEGMENT CABLETRUNKINGSEGMENT CONDUITSEGMENT',
    'DistributionElement': None, 'Site': None, 'Building': None,
    'BuildingStorey': None,
    'SpatialZone': 'CONSTRUCTION FIRESAFETY LIGHTING OCCUPANCY SECURITY THERMAL TRANSPORT VENTILATION',
    'Facility': None, 'FacilityPart': None,
}
IFC_CLASSES = ['Ifc' + key for key in _ENUMS]
TABLES = {}
for name, members in _ENUMS.items():
    schemas = SCHEMAS[1:] if name in ('Facility', 'FacilityPart') else SCHEMAS
    values = [] if members is None else (members.split() + ['USERDEFINED', 'NOTDEFINED'])
    TABLES['Ifc' + name] = {
        'schemas': list(schemas),
        'predefined_types': {schema: list(values) for schema in schemas},
        'common': {},
    }
# Curated property templates: only facts explicitly supported by this editor.
for name in ('Wall Slab Column Beam Footing Roof Stair Ramp Door Window Railing Covering Pile Member Plate CurtainWall BuildingElementProxy').split():
    TABLES['Ifc' + name]['common'] = {
        'Reference': {'kind': 'label'}, 'Status': {'kind': 'enum', 'members': STATUS},
        'IsExternal': {'kind': 'boolean'}, 'FireRating': {'kind': 'label'},
    }
for name in ('Wall Slab Column Beam Footing Pile Member Plate') .split():
    TABLES['Ifc' + name]['common']['LoadBearing'] = {'kind': 'boolean'}

def predefined_types(ifc_class, schema='IFC4'):
    return list(TABLES.get(ifc_class, {}).get('predefined_types', {}).get(schema, []))

def common_pset(ifc_class):
    return 'Pset_' + ifc_class.removeprefix('Ifc') + 'Common'
