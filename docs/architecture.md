# IngeTrazo architecture

This is an early-stage document. Expect it to grow as the codebase does.

## High-level layout

```
ingetrazo/
├── main.py            ← Qt application entry point
├── core/              ← scene graph, camera, geometry primitives, layers
├── views/             ← Qt widgets: main window, viewport, panels
├── tools/             ← built-in modeling tools (line, rectangle, push/pull, ...)
├── plugins/           ← third-party tools, discovered at startup
├── georef/            ← real-world location: tiles, DEM, projections
├── styles/            ← visual style presets (shader modes)
├── materials/         ← material library and editor
├── analysis/          ← (future) 3D-printing checks: manifold, thickness, overhangs
├── formats/           ← import / export for OBJ, COLLADA, glTF, STL, IFC (3MF planned)
├── i18n/              ← UI translations (en, es, ...)
├── resources/         ← shaders, icons, fonts, stylesheets
└── tests/             ← automated tests
```

## Rendering pipeline

The 3D viewport uses **QOpenGLWidget** (PySide6) as the Qt-managed surface and **ModernGL** as the Python-friendly wrapper around OpenGL 3.3+. Shaders live in `resources/shaders/` and are loaded by the `styles/` modules.

## Scene graph

To be documented.

## Plugin system

See [plugins.md](plugins.md).

## Semantic objects and project metadata

Placed groups own versioned JSON [object records](object-record.md) in `group.ifc`.
The [project registry](project-registry.md) defines classification namespaces,
shared types, systems and export profiles in scene plugin data. `core.record`
provides detached normalization, validation and type resolution; `core.ifc_tables`
holds hand-written schema facts. History commands own persisted metadata edits
and advance revisions without invalidating geometry caches. Loose-face BIM tags
remain the minimal legacy representation.
