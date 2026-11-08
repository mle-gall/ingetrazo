# SPDX-License-Identifier: GPL-3.0-or-later
"""Generated vocabulary and hand-written common-property facts; no redistributed EXPRESS or XML.

References: buildingSMART IFC4 ADD2 TC1 and IFC4.3 ADD2 lexical documentation.
An empty enumeration means the entity has no PredefinedType attribute.
Common templates describe IFC4 properties, not a complete IFC validator.
"""
SCHEMAS = ('IFC4', 'IFC4X3_ADD2')
STATUS = 'NEW EXISTING DEMOLISH TEMPORARY OTHER NOTKNOWN UNSET'.split()
_ENUMS = {
    'Wall': 'MOVABLE PARAPET PARTITIONING PLUMBINGWALL SHEAR SOLIDWALL STANDARD POLYGONAL ELEMENTEDWALL',
    'Slab': 'FLOOR ROOF LANDING BASESLAB',
    'Column': 'COLUMN PILASTER', 'Beam': 'BEAM JOIST HOLLOWCORE LINTEL SPANDREL T_BEAM',
    'Footing': 'CAISSON_FOUNDATION FOOTING_BEAM PAD_FOOTING PILE_CAP STRIP_FOOTING',
    'Roof': 'FLAT_ROOF SHED_ROOF GABLE_ROOF HIP_ROOF HIPPED_GABLE_ROOF GAMBREL_ROOF MANSARD_ROOF BARREL_ROOF RAINBOW_ROOF BUTTERFLY_ROOF PAVILION_ROOF DOME_ROOF FREEFORM',
    'Stair': 'STRAIGHT_RUN_STAIR TWO_STRAIGHT_RUN_STAIR QUARTER_WINDING_STAIR QUARTER_TURN_STAIR HALF_WINDING_STAIR HALF_TURN_STAIR TWO_QUARTER_WINDING_STAIR TWO_QUARTER_TURN_STAIR THREE_QUARTER_WINDING_STAIR THREE_QUARTER_TURN_STAIR SPIRAL_STAIR DOUBLE_RETURN_STAIR CURVED_RUN_STAIR TWO_CURVED_RUN_STAIR',
    'Ramp': 'STRAIGHT_RUN_RAMP TWO_STRAIGHT_RUN_RAMP QUARTER_TURN_RAMP TWO_QUARTER_TURN_RAMP HALF_TURN_RAMP SPIRAL_RAMP',
    'Door': 'DOOR GATE TRAPDOOR', 'Window': 'WINDOW SKYLIGHT LIGHTDOME',
    'Railing': 'HANDRAIL GUARDRAIL BALUSTRADE',
    'Covering': 'CEILING FLOORING CLADDING ROOFING MOLDING SKIRTINGBOARD INSULATION MEMBRANE SLEEVING WRAPPING',
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
from core.ifc_tables_data import SCHEMA_DATA

IFC_CLASSES += sorted(set().union(*(d['classes'] for d in SCHEMA_DATA.values())) - set(IFC_CLASSES))
TABLES = {}
for cls in IFC_CLASSES:
    entries = {schema: data['classes'][cls] for schema, data in SCHEMA_DATA.items() if cls in data['classes']}
    exemplar = next(iter(entries.values()))
    TABLES[cls] = {
        'schemas': list(entries), 'common': {},
        'predefined_types': {schema: entry['predefined_types'] for schema, entry in entries.items()},
        'domain': exemplar['domain'],
        'type_class': {schema: entry['type_class'] for schema, entry in entries.items()},
        'enum_name': {schema: entry['enum_name'] for schema, entry in entries.items()},
    }

# IFC4 Common templates. Empty means no Pset_<Class>Common exists.
# Scalar measures outside length/area/volume use real; see the record contract.
_COMMON = {
    'Wall': 'Reference:label Status:enum AcousticRating:label FireRating:label Combustible:boolean SurfaceSpreadOfFlame:label ThermalTransmittance:real IsExternal:boolean LoadBearing:boolean ExtendToStructure:boolean Compartmentation:boolean',
    'Slab': 'Reference:label Status:enum AcousticRating:label FireRating:label PitchAngle:real Combustible:boolean SurfaceSpreadOfFlame:label Compartmentation:boolean IsExternal:boolean ThermalTransmittance:real LoadBearing:boolean',
    'Column': 'Reference:label Status:enum Slope:real Roll:real IsExternal:boolean ThermalTransmittance:real LoadBearing:boolean FireRating:label',
    'Beam': 'Reference:label Status:enum Span:length Slope:real Roll:real IsExternal:boolean ThermalTransmittance:real LoadBearing:boolean FireRating:label',
    'Footing': 'Reference:label Status:enum LoadBearing:boolean',
    'Roof': 'Reference:label Status:enum AcousticRating:label IsExternal:boolean ThermalTransmittance:real LoadBearing:boolean FireRating:label',
    'Stair': 'Reference:label Status:enum NumberOfRiser:integer NumberOfTreads:integer RiserHeight:length TreadLength:length NosingLength:length WalkingLineOffset:length TreadLengthAtOffset:length TreadLengthAtInnerSide:length WaistThickness:length RequiredHeadroom:length HandicapAccessible:boolean HasNonSkidSurface:boolean IsExternal:boolean ThermalTransmittance:real LoadBearing:boolean FireRating:label FireExit:boolean',
    'Ramp': 'Reference:label Status:enum RequiredHeadroom:length RequiredSlope:real HandicapAccessible:boolean HasNonSkidSurface:boolean FireExit:boolean IsExternal:boolean ThermalTransmittance:real LoadBearing:boolean FireRating:label',
    'Door': 'Reference:label Status:enum FireRating:label AcousticRating:label SecurityRating:label DurabilityRating:label HygrothermalRating:label WaterTightnessRating:label MechanicalLoadRating:label WindLoadRating:label Infiltration:real IsExternal:boolean ThermalTransmittance:real GlazingAreaFraction:real HandicapAccessible:boolean FireExit:boolean HasDrive:boolean SelfClosing:boolean SmokeStop:boolean',
    'Window': 'Reference:label Status:enum AcousticRating:label FireRating:label SecurityRating:label IsExternal:boolean Infiltration:real ThermalTransmittance:real GlazingAreaFraction:real HasSillExternal:boolean HasSillInternal:boolean HasDrive:boolean SmokeStop:boolean FireExit:boolean WaterTightnessRating:label MechanicalLoadRating:label WindLoadRating:label',
    'Railing': 'Reference:label Status:enum Height:length Diameter:length IsExternal:boolean',
    'Covering': 'Reference:label Status:enum AcousticRating:label FlammabilityRating:label FragilityRating:label Combustible:boolean SurfaceSpreadOfFlame:label Finish:text IsExternal:boolean ThermalTransmittance:real FireRating:label',
    'Space': 'Reference:label IsExternal:boolean GrossPlannedArea:area NetPlannedArea:area PubliclyAccessible:boolean HandicapAccessible:boolean',
    'ReinforcingBar': 'Reference:label Status:enum NominalDiameter:length BarLength:length BarSpacing:length BarSurface:enum BendingShapeCode:label BendingParameters:text',
    'BuildingElementProxy': 'Reference:label Status:enum IsExternal:boolean ThermalTransmittance:real LoadBearing:boolean FireRating:label',
    'ElementAssembly': 'Reference:label Status:enum',
    'CurtainWall': 'Reference:label Status:enum AcousticRating:label FireRating:label Combustible:boolean SurfaceSpreadOfFlame:label ThermalTransmittance:real IsExternal:boolean',
    'Plate': 'Reference:label Status:enum AcousticRating:label IsExternal:boolean ThermalTransmittance:real LoadBearing:boolean FireRating:label',
    'TransportElement': 'Reference:label Status:enum CapacityPeople:integer CapacityWeight:real FireExit:boolean',
    'MechanicalFastener': 'NominalDiameter:length NominalLength:length',
    'Site': 'Reference:label BuildableArea:area SiteCoverageRatio:real FloorAreaRatio:real BuildingHeightLimit:length TotalArea:area',
    'Building': 'Reference:label BuildingID:label IsPermanentID:boolean ConstructionMethod:label FireProtectionClass:label SprinklerProtection:boolean SprinklerProtectionAutomatic:boolean OccupancyType:label GrossPlannedArea:area NetPlannedArea:area NumberOfStoreys:integer YearOfConstruction:label YearOfLastRefurbishment:label IsLandmarked:enum',
    'BuildingStorey': 'Reference:label EntranceLevel:boolean AboveGround:enum SprinklerProtection:boolean SprinklerProtectionAutomatic:boolean LoadBearingCapacity:real GrossPlannedArea:area NetPlannedArea:area',
    'SpatialZone': 'Reference:label IsExternal:boolean',
}
# Additional IFC4 common property names, independently checked by the
# optional IfcOpenShell oracle. No library definitions or descriptions ship.
_COMMON.update({
    'BuildingSystem': 'Reference:label',
    'DistributionSystem': 'Reference:label',
    'Chimney': 'Reference:label Status:enum NumberOfDrafts:integer IsExternal:boolean ThermalTransmittance:real LoadBearing:boolean FireRating:label',
    'CivilElement': 'Reference:label Status:enum',
    'DistributionChamberElement': 'Reference:label Status:enum',
    'OpeningElement': 'Reference:label Status:enum Purpose:label FireExit:boolean ProtectedOpening:boolean',
    'RampFlight': 'Reference:label Status:enum Headroom:length ClearWidth:length Slope:real CounterSlope:real',
    'ReinforcingMesh': 'Reference:label Status:enum MeshLength:length MeshWidth:length LongitudinalBarNominalDiameter:length LongitudinalBarSpacing:length LongitudinalBarSurface:enum TransverseBarNominalDiameter:length TransverseBarSpacing:length TransverseBarSurface:enum TransverseBarBendingShapeCode:label TransverseBarBendingParameters:text',
    'ShadingDevice': 'Reference:label Status:enum ShadingDeviceType:enum MechanicalOperated:boolean SolarTransmittance:real SolarReflectance:real VisibleLightTransmittance:real VisibleLightReflectance:real ThermalTransmittance:real IsExternal:boolean Roughness:label SurfaceColor:label',
    'StairFlight': 'Reference:label Status:enum NumberOfRiser:integer NumberOfTreads:integer RiserHeight:length TreadLength:length NosingLength:length WalkingLineOffset:length TreadLengthAtOffset:length TreadLengthAtInnerSide:length Headroom:length WaistThickness:length',
    'Tendon': 'Reference:label Status:enum NominalDiameter:length SheathDiameter:length',
    'TendonAnchor': 'Reference:label Status:enum',
    'Zone': _COMMON['Space'],
})
_COMMON['Member'] = _COMMON['Beam']
_COMMON['Pile'] = _COMMON['Footing']
for name, properties in _COMMON.items():
    template = TABLES['Ifc' + name]['common']
    for field in properties.split():
        prop, kind = field.split(':')
        template[prop] = {'kind': kind}
        if prop == 'Status':
            template[prop]['members'] = list(STATUS)
        elif prop in ('AboveGround', 'IsLandmarked'):
            template[prop]['members'] = ['TRUE', 'FALSE', 'UNKNOWN']
        elif prop == 'ShadingDeviceType':
            template[prop]['members'] = ['FIXED', 'MOVABLE', 'OVERHANG', 'SIDEFIN', 'OTHER', 'NOTKNOWN', 'UNSET']
        elif prop in ('BarSurface', 'LongitudinalBarSurface', 'TransverseBarSurface'):
            template[prop]['members'] = ['PLAIN', 'TEXTURED', 'OTHER', 'USERDEFINED', 'NOTDEFINED']
# The v1 scalar record cannot encode IFC list-valued bending parameters.
TABLES['IfcReinforcingBar']['common']['BendingParameters']['scalar_only'] = False
TABLES['IfcReinforcingMesh']['common']['TransverseBarBendingParameters']['scalar_only'] = False

def predefined_types(ifc_class, schema='IFC4'):
    return list(TABLES.get(ifc_class, {}).get('predefined_types', {}).get(schema, []))

def common_pset(ifc_class):
    return 'Pset_' + ifc_class.removeprefix('Ifc') + 'Common'
