# SPDX-License-Identifier: GPL-3.0-or-later
"""Attribute order is explicit so schema drift fails before a file is written.

These are hand-written interoperability facts, not bundled EXPRESS definitions.
"""
from .step import _Writer

ROOT = 'GlobalId OwnerHistory Name Description'
OBJECT = ROOT + ' ObjectType'
PRODUCT = OBJECT + ' ObjectPlacement Representation'
ELEMENT = PRODUCT + ' Tag'
SPATIAL = PRODUCT + ' LongName CompositionType'
TYPE = ROOT + ' ApplicableOccurrence HasPropertySets RepresentationMaps Tag ElementType'
ORDERS = {}
def register(names, attrs):
    for name in names.split():
        ORDERS['IFC' + name.upper()] = attrs.split()

register('Wall Slab Column Beam Footing Roof Stair Ramp Railing Covering Member BuildingElementProxy BuildingElementPart CurtainWall Plate TransportElement GeographicElement DiscreteAccessory Fastener PipeSegment DuctSegment CableCarrierSegment', ELEMENT + ' PredefinedType')
register('FurnishingElement FlowSegment FlowFitting FlowTerminal DistributionElement', ELEMENT)
register('Pile', ELEMENT + ' PredefinedType ConstructionType')
register('Door Window', ELEMENT + ' OverallHeight OverallWidth PredefinedType OperationType UserDefinedOperationType')
ORDERS['IFCWINDOW'][-2:] = ['PartitioningType', 'UserDefinedPartitioningType']
register('ReinforcingBar', ELEMENT + ' SteelGrade NominalDiameter CrossSectionArea BarLength PredefinedType BarSurface')
register('MechanicalFastener', ELEMENT + ' NominalDiameter NominalLength PredefinedType')
register('ElementAssembly', ELEMENT + ' AssemblyPlace PredefinedType')
register('Site', SPATIAL + ' RefLatitude RefLongitude RefElevation LandTitleNumber SiteAddress')
register('Building', SPATIAL + ' ElevationOfRefHeight ElevationOfTerrain BuildingAddress')
register('BuildingStorey', SPATIAL + ' Elevation')
register('Space', SPATIAL + ' PredefinedType ElevationWithFlooring')
register('SpatialZone', PRODUCT + ' LongName PredefinedType')
register('Facility', SPATIAL)
register('FacilityPart', SPATIAL + ' UsageType')
register('FacilityPartCommon', SPATIAL + ' UsageType PredefinedType')
register('Group System', OBJECT)
register('Zone', OBJECT + ' LongName')
register('DistributionSystem', OBJECT + ' LongName PredefinedType')
register('Project', OBJECT + ' LongName Phase RepresentationContexts UnitsInContext')
for cls in list(ORDERS):
    if cls.startswith('IFC') and 'Tag' in ORDERS[cls]:
        ORDERS[cls + 'TYPE'] = (TYPE + ' PredefinedType').split()
register('SpaceType SpatialZoneType', TYPE + ' PredefinedType LongName')
register('DoorType', TYPE + ' PredefinedType OperationType ParameterTakesPrecedence UserDefinedOperationType')
register('WindowType', TYPE + ' PredefinedType PartitioningType ParameterTakesPrecedence UserDefinedPartitioningType')
register('ReinforcingBarType', TYPE + ' PredefinedType NominalDiameter CrossSectionArea BarLength BarSurface BendingShapeCode BendingParameters')
register('FurnishingElementType FlowSegmentType FlowFittingType FlowTerminalType DistributionElementType', TYPE)
register('MechanicalFastenerType', TYPE + ' PredefinedType NominalDiameter NominalLength')
register('RelAggregates', ROOT + ' RelatingObject RelatedObjects')
register('RelContainedInSpatialStructure', ROOT + ' RelatedElements RelatingStructure')
register('RelDefinesByProperties', ROOT + ' RelatedObjects RelatingPropertyDefinition')
register('RelDefinesByType', ROOT + ' RelatedObjects RelatingType')
register('RelAssociatesClassification', ROOT + ' RelatedObjects RelatingClassification')
register('RelAssignsToGroup', ROOT + ' RelatedObjects RelatedObjectsType RelatingGroup')
register('PropertySet', ROOT + ' HasProperties')
register('PropertySingleValue', 'Name Description NominalValue Unit')
register('ElementQuantity', ROOT + ' MethodOfMeasurement Quantities')
for kind in ('Length', 'Area', 'Volume', 'Weight', 'Count'):
    register('Quantity' + kind, 'Name Description Unit ' + kind + 'Value Formula')
register('Classification', 'Source Edition EditionDate Name Description Location ReferenceTokens')
register('ClassificationReference', 'Location Identification Name ReferencedSource Description Sort')
register('Person', 'Identification FamilyName GivenName MiddleNames PrefixTitles SuffixTitles Roles Addresses')
register('Organization', 'Identification Name Description Roles Addresses')
register('PersonAndOrganization', 'ThePerson TheOrganization Roles')
register('Application', 'ApplicationDeveloper Version ApplicationFullName ApplicationIdentifier')
register('OwnerHistory', 'OwningUser OwningApplication State ChangeAction LastModifiedDate LastModifyingUser LastModifyingApplication CreationDate')
register('CartesianPoint', 'Coordinates')
register('Axis2Placement3D', 'Location Axis RefDirection')
register('LocalPlacement', 'PlacementRelTo RelativePlacement')
register('GeometricRepresentationContext', 'ContextIdentifier ContextType CoordinateSpaceDimension Precision WorldCoordinateSystem TrueNorth')
register('GeometricRepresentationSubContext', 'ContextIdentifier ContextType CoordinateSpaceDimension Precision WorldCoordinateSystem TrueNorth ParentContext TargetScale TargetView UserDefinedTargetView')
register('SIUnit', 'Dimensions UnitType Prefix Name')
register('UnitAssignment', 'Units')
register('PolyLoop', 'Polygon')
register('FaceOuterBound FaceBound', 'Bound Orientation')
register('Face', 'Bounds')
register('ClosedShell OpenShell', 'CfsFaces')
register('FacetedBrep', 'Outer')
register('ShellBasedSurfaceModel', 'SbsmBoundary')
register('ShapeRepresentation', 'ContextOfItems RepresentationIdentifier RepresentationType Items')
register('ProductDefinitionShape', 'Name Description Representations')

class Builder(_Writer):
    def __init__(self, schema):
        super().__init__()
        self.schema = schema

    def attributes(self, entity):
        attrs = ORDERS[entity.upper()]
        if self.schema == 'IFC4X3_ADD2':
            if entity.upper() == 'IFCPROPERTYSINGLEVALUE':
                return ['Specification' if a == 'Description' else a for a in attrs]
            if entity.upper() == 'IFCCLASSIFICATION':
                return ['Specification' if a == 'Location' else a for a in attrs]
        return attrs

    def add(self, entity, *attrs):
        if len(attrs) != len(self.attributes(entity)):
            raise ValueError('Wrong attribute count for ' + entity)
        return super().add(entity.upper(), *attrs)

    def entity(self, entity, **values):
        attrs = self.attributes(entity)
        unknown = values.keys() - set(attrs)
        if unknown:
            raise ValueError(f'{entity}: unknown attributes {unknown}')
        return self.add(entity, *(values.get(key, '$') for key in attrs))
