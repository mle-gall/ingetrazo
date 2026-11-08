# SPDX-License-Identifier: GPL-3.0-or-later
"""Hand-written interoperability facts; no redistributed EXPRESS or XML.

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
TABLES = {}
for name, members in _ENUMS.items():
    schemas = SCHEMAS[1:] if name in ('Facility', 'FacilityPart') else SCHEMAS
    values = [] if members is None else (members.split() + ['USERDEFINED', 'NOTDEFINED'])
    TABLES['Ifc' + name] = {
        'schemas': list(schemas),
        'predefined_types': {schema: list(values) for schema in schemas},
        'common': {},
    }
# IFC4.3 ADD2 extends these occurrence enumerations.
_ADDITIONS_43 = {
    'Wall': 'RETAININGWALL WAVEWALL',
    'Slab': 'APPROACH_SLAB PAVING SIDEWALK TRACKSLAB WEARING',
    'Column': 'PIERSTEM PIERSTEM_SEGMENT STANDCOLUMN',
    'Beam': 'CORNICE DIAPHRAGM EDGEBEAM GIRDER_SEGMENT HATSTONE PIERCAP',
    'Stair': 'LADDER', 'Door': 'BOOM_BARRIER TURNSTILE', 'Railing': 'FENCE',
    'Covering': 'COPING TOPPING',
    'Member': 'ARCH_SEGMENT STAY_CABLE STIFFENING_RIB STRUCTURALCABLE SUSPENDER SUSPENSION_CABLE TIEBAR',
    'Space': 'BERTH', 'ReinforcingBar': 'SPACEBAR',
    'ElementAssembly': 'ABUTMENT CROSS_BRACING DECK DILATATIONPANEL ENTRANCEWORKS GRID MAST PIER PYLON RAIL_MECHANICAL_EQUIPMENT_ASSEMBLY SHELTER SIGNALASSEMBLY SUMPBUSTER SUPPORTINGASSEMBLY SUSPENSIONASSEMBLY TRACKPANEL TRACTION_SWITCHING_ASSEMBLY TRAFFIC_CALMING_DEVICE TURNOUTPANEL',
    'BuildingElementPart': 'APRON ARMOURUNIT SAFETYCAGE',
    'Plate': 'BASE_PLATE COVER_PLATE FLANGE_PLATE GUSSET_PLATE SPLICE_PLATE STIFFENER_PLATE WEB_PLATE',
    'TransportElement': 'HAULINGGEAR', 'GeographicElement': 'SOIL_BORING_POINT VEGETATION',
    'DiscreteAccessory': 'BIRDPROTECTION CABLEARRANGER ELASTIC_CUSHION EXPANSION_JOINT_DEVICE FILLER FLASHING INSULATOR LOCK PANEL_STRENGTHENING POINTMACHINEMOUNTINGDEVICE POINT_MACHINE_LOCKING_DEVICE RAILBRACE RAILPAD RAIL_LUBRICATION RAIL_MECHANICAL_EQUIPMENT SLIDINGCHAIR SOUNDABSORPTION TENSIONINGEQUIPMENT',
    'MechanicalFastener': 'CHAIN COUPLER RAILFASTENING RAILJOINT ROPE',
    'CableCarrierSegment': 'CABLEBRACKET CATENARYWIRE DROPPER',
    'SpatialZone': 'INTERFERENCE RESERVATION',
}
for name, additions in _ADDITIONS_43.items():
    TABLES['Ifc' + name]['predefined_types']['IFC4X3_ADD2'] += additions.split()

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
        elif prop == 'BarSurface':
            template[prop]['members'] = ['PLAIN', 'TEXTURED', 'OTHER', 'USERDEFINED', 'NOTDEFINED']
# The v1 scalar record cannot encode IFC list-valued bending parameters.
TABLES['IfcReinforcingBar']['common']['BendingParameters']['scalar_only'] = False

def predefined_types(ifc_class, schema='IFC4'):
    return list(TABLES.get(ifc_class, {}).get('predefined_types', {}).get(schema, []))

def common_pset(ifc_class):
    return 'Pset_' + ifc_class.removeprefix('Ifc') + 'Common'
