# AI Bridge — modelar con Claude (MCP)

IngeTrazo puede ser dirigido por un agente de IA (Claude Code, Claude
Desktop) mediante el [Model Context Protocol](https://modelcontextprotocol.io):
el agente dibuja, consulta y **ve** el modelo en vivo — y cada acción suya
es un paso de undo transaccional (si su código falla, el documento se
revierte entero; el guard de hermeticidad valida sus recetas).

## Uso

1. En IngeTrazo: pestaña **IA** de la barra lateral ▸ sección **Puente IA
   (MCP)** ▸ **Encender puente** (o **Extensiones ▸ Puente IA (MCP)**, que
   abre esa sección y lo enciende) — arranca un servidor local (solo
   127.0.0.1, puerto 4763; `INGETRAZO_AI_PORT` lo cambia). **Detener
   puente** lo apaga.
2. Al encenderlo, la sección muestra, con un botón Copiar, las líneas exactas para
   tu sistema (botón **Copiar**). No hace falta tener Python instalado: el
   paquete lleva el servidor MCP.

   | Instalación | Comando del servidor MCP |
   |---|---|
   | Windows (instalador o zip) | `C:\Program Files\IngeTrazo\ingetrazo-mcp.exe` |
   | Linux AppImage / tarball / Flatpak / snap | `<ejecutable de IngeTrazo> --mcp` |
   | Desde el repositorio | `python3 /ruta/a/app/scripts/ingetrazo_mcp.py` |

   **Claude Code** (en una terminal):

       claude mcp add ingetrazo -- "C:\Program Files\IngeTrazo\ingetrazo-mcp.exe"

   **Claude Desktop**: pega esto en su archivo de configuración
   (`%APPDATA%\Claude\claude_desktop_config.json` en Windows,
   `~/.config/Claude/claude_desktop_config.json` en Linux) y reinicia
   Claude Desktop:

       {
         "mcpServers": {
           "ingetrazo": {
             "command": "C:\\Program Files\\IngeTrazo\\ingetrazo-mcp.exe",
             "args": []
           }
         }
       }

   Si Claude no responde: comprueba que IngeTrazo sigue abierto con el
   puente encendido (la sección Puente IA (MCP) dice «Escuchando en…»),
   que la ruta del comando existe, y en Claude Desktop que el servidor
   aparece en Configuración ▸ Desarrollador ▸ MCP sin error.
3. Pídele cosas: *"dibuja una casita de 6×4 m con techo a dos aguas,
   agrúpala y píntala de ladrillo; muéstrame cómo quedó"*.

### El agente dentro de un contenedor (Docker, WSL2)

El puente escucha **solo en `127.0.0.1`** de la máquina donde corre
IngeTrazo, y así se queda: no tiene contraseña y `run_python` ejecuta
código dentro de la aplicación, de modo que abrirlo a la red dejaría el
modelo (y el equipo) a merced de cualquiera en ella.

Escuchar en local no basta frente al navegador del mismo equipo: una página
web puede mandar un `POST` a `http://127.0.0.1:4763` sin que el navegador
pida permiso (`fetch` con `mode: "no-cors"` y cuerpo de texto). Por eso el
puente corta la conexión en la primera línea que no es una petición JSON —
la primera línea de cualquier petición HTTP es `POST / HTTP/1.1` — y el
cuerpo nunca llega a leerse. Aun así, **detén el puente cuando no lo uses**.

- **IngeTrazo dentro de WSL2** (AppImage o `.tar.gz` con WSLg) y el
  contenedor con `--network host`: funciona tal cual, porque comparten
  `127.0.0.1`.
- **En cualquier otro caso**, lleva el puerto hasta el agente con un túnel
  que tú controlas (`ssh -L 4763:127.0.0.1:4763 usuario@equipo`, `socat`…)
  y dile al cliente MCP dónde está el otro extremo:

      INGETRAZO_AI_HOST=host.docker.internal INGETRAZO_AI_PORT=4763 \
          python3 /ruta/a/app/scripts/ingetrazo_mcp.py

  `INGETRAZO_AI_HOST` (por defecto `127.0.0.1`) solo cambia a dónde se
  conecta el cliente; el puente no deja de escuchar únicamente en local.

## Herramientas expuestas

| Tool | Qué hace |
|---|---|
| `run_python` | Ejecuta Python sobre el documento vivo (scope: `scene`, `mesh`, `selection`, `groups`, `bim`, `QVector3D`… y los constructores `revolve(perfil)` / `extrude(contorno, z0, z1)`: una línea → un grupo sólido, suave y orientado). Un undo por llamada; rollback total si falla. |
| `query_model` | Conteos, nombres de grupos/componentes, materiales, capas, bounds. |
| `query_groups` / `query_tree` / `query_entity` | Grupos por nombre, árbol paginado y detalles por uid. |
| `query_selection` / `select` | Inspecciona o cambia la selección por uid o patrón de nombre. |
| `query_layers` / `set_layer_visibility` | Capas, carpetas y visibilidad (usa el historial de estados de capas). |
| `query_camera` / `set_camera` / `zoom_to` | Consulta y dirige la cámara; encuadra grupos o la selección. |
| `query_changes` / `query_status` | Cambios desde una revisión y variables JSON publicadas. |
| `query_record` / `query_records` | Fichas, tipos resueltos, problemas de validación y grupos sin clasificar; paginación y totales. |
| `query_vocabulary` / `query_registry` | Clases, propiedades comunes y vocabulario del registro del proyecto. |
| `set_record` / `tag` / `untag` | Edita las fichas de varios grupos en un paso de undo; valida antes de aplicar. |
| `add_classification` / `remove_classification` | Combina o elimina clasificaciones por objeto en un paso de undo. |
| `set_registry` / `add_classification_system` / `import_classification_codes` | Sustituye el registro, añade un espacio de clasificación o importa códigos CSV. |
| `set_type` / `set_system` | Crea o sustituye tipos y sistemas del proyecto. |
| `delete_type` / `delete_system` / `delete_classification_system` | Elimina entradas; rechaza referencias activas salvo con `force=true`. |
| `export_ifc` | Exporta el IFC con un perfil del registro y devuelve el recuento, las fichas omitidas con su motivo y el resultado IDS. |
| `list_tools` | Catálogo vivo, incluidas las herramientas de extensiones. |
| `screenshot` | Renderiza el viewport real; `uids` encuadra grupos antes de capturar y devuelve la cámara usada. |
| `undo` / `redo` | La historia de siempre. |

Sin el puente encendido, las tools responden con el aviso de cómo
encenderlo. El servidor acepta un cliente a la vez y nunca escucha fuera
de localhost.

## Fast inspection and incremental refresh (agent API)

Use the structured read-only tools instead of `run_python` for inspection:

- `query_model(include_bounds=false)` returns the overview and scene version
  without walking the model for bounds. Omitting the option preserves the
  existing response with bounds.
- `query_groups(name="saddle", offset=0, limit=100)` searches nested group
  names (case insensitive), returning uid paths, layer, visibility and child
  counts. Follow `next_offset` until null. If `version` changes between pages,
  restart the traversal because the live document changed.
- `query_status(name="job_status")` reads a plain JSON variable previously
  assigned in `run_python`'s persistent scope, e.g.
  `job_status = {"done": True}`. Missing variables return `found=false`.
  Objects, Python expressions and private names are not accepted. Status
  stored elsewhere (e.g. `builtins`) must first be explicitly published in
  this scope by the recipe.

These tools execute on the main thread but do not capture undo snapshots,
run arbitrary Python, bake geometry or request a redraw. They still wait
when the main thread is busy; they cannot interrupt an in-progress edit.

Normal `run_python` recipes refresh automatically. For a deferred callback
that executes its own undoable command, finish the batch with:

```python
viewport.history.execute(command)
viewport.refresh_after_edit()
```

This uses the renderer's existing per-mesh/material/placement validation,
retaining unchanged geometry and GPU caches. Commands must bump
`scene.version` and use the supported mesh mutation APIs, including their
attribute dirty flags. Raw writes bypassing those APIs are not supported by
this refresh contract. Undo and redo must follow the same mutation contract.
Do not call `reset_document_caches()` for local edits: it is for New/Open.
Do not refresh in the middle of an interactive transform preview.

Updating a checkout does not update an already-running packaged application.
Use a build containing these changes and reconnect the MCP client to expose
the new tool schemas. Existing scripts must replace their explicit full
reset with `refresh_after_edit()`; this does not rewrite them automatically.

## Asistente IA (dentro de la app)

Para el usuario que no usa Claude Code: la pestaña **IA** de la barra
lateral (Ctrl+Shift+A la trae al frente, aunque esté oculta) es un chat
DENTRO de IngeTrazo. Pega tu clave API — el
proveedor se detecta solo por el prefijo, la convención de IngePresupuestos:

| Prefijo | Proveedor | Modelo por defecto |
|---|---|---|
| `sk-ant-` | Anthropic | claude-sonnet-5 |
| `gsk_` | Groq (gratis) | llama-3.3-70b-versatile |
| `sk-or-` | OpenRouter | anthropic/claude-sonnet-5 |
| `AIza` | Gemini | gemini-2.5-flash |
| `sk-` | OpenAI | gpt-4o |
| *(vacía)* | Ollama local | qwen2.5-coder:7b |

Escribe qué quieres ("dibuja una casa de 6×4 con techo a dos aguas") y el
asistente actúa por recetas de Python transaccionales — cada acción es un
paso de undo, y con proveedores con visión recibe capturas del viewport
para VER lo que construyó e iterar. El modelo es editable, y la clave se
guarda en la configuración local.

### Modelar desde una foto

Con el botón **Foto…** adjuntas la imagen de un objeto (una fuente, un
mueble, una fachada) y el asistente la interpreta y lo recrea por partes,
cada una como grupo con nombre, comparando sus capturas contra la foto.
Dale las medidas reales en el mensaje ("la taza mide 4 m de diámetro, el
alto total 2,30") — una foto no trae dimensiones, y lo que el asistente
estime del ojo lo declara como supuesto para que lo corrijas. La foto se
reescala a 1280 px y viaja como JPEG solo en ese mensaje. Necesita un
proveedor con visión (Anthropic, OpenAI, Gemini, OpenRouter).

### Command changes since a revision

`query_changes(since_revision=0)` is read-only. It returns:

```json
{"revision": 12, "complete": true,
 "changes": [{"revision": 12, "phase": "undo", "command": "FlipFacesCommand"}]}
```

The token belongs to the current document's **History**, independently of
`scene.version`, `scene.revision` and `mesh.revision`. Start from zero after
New/Open or switching documents; pass the last returned revision to poll.
The last 256 successful execute/undo/redo operations are retained. If older
entries expired, `complete=false` means a full model refresh is required.
Clearing undo stacks does not rewind this token. Invalid/future revisions are
rejected. Failures, rejected commands, and writes outside History are not
journal entries. Entries name command classes, not geometric diffs or a
complete affected-entity set. No snapshots, redraws or geometry builds occur.

An agent maintaining a parametric or intent record can use this journal to
decide when to recheck its inputs, then compare a group's mesh identity and
`mesh.revision` to mark the record stale after external edits. Its own rebuild
should update the remembered token. Direct element edits must call
`mesh.mark_modified()` once per batch (see the plugin documentation).

## Dynamic tools and document navigation

MCP `tools/list` requests the bridge's live registry every time, so extensions
can publish tools without changing the MCP script. When the bridge is offline,
the client returns the shared built-in schema catalog. Re-list tools after an
extension registers or unsubscribes; this server does not emit list-change
notifications. Calls remain generic and keep the existing bridge error format.

`query_tree(root_uid=None, depth=2, offset=0, limit=200, include_hidden=True)`
returns `rows`, `total`, `next_offset` and `version`. Order is depth-first in
scene/child order. Roots have depth zero; a supplied root is included at depth
zero. Hidden filtering prunes explicitly hidden ancestors. Layer visibility is
reported separately. Restart paging when the scene version changes.

`query_entity(uid)` returns the tree metadata plus world bounds, column-major
local and world placement matrices, direct mesh face/edge counts, material
names, child uids and ancestor names. IFC data is passed through unchanged.
`shared_definition_key` identifies shared meshes for this bridge session; it
is not a persisted document identifier. Use group uids across sessions.

`query_selection` returns counts by Python entity kind, group rows, direct
face/edge selection counts and combined world bounds. `select` accepts uids,
name globs (`names` or `pattern`, case-sensitive), and replace/add/remove/clear.
Unknown uids fail before selection changes. Selection and camera changes do
not create document undo entries.

`query_layers` counts direct group tags and faces across unique meshes (shared
component faces count once), with folder paths ordered from root to leaf.
`set_layer_visibility` accepts layer uids or names and uses the Layers panel's
existing display-state history: restore with **Previous layer state**, not
geometry undo. It also releases a hidden active layer and prunes selection.

`set_camera` accepts standard presets (top, bottom, front, back, left, right,
iso), eye/target/up vectors and `ortho`. Explicit vectors use the camera's
existing look-from navigation, including its near-pole constraint; a preset
wins over an explicit orientation. `zoom_to` frames supplied group uids,
otherwise the selection, otherwise the model. An explicit empty uid list is
a no-op. Screenshots render synchronously through `render_image`; optional
uids frame first, and the response includes the camera used. MCP returns the
image with camera metadata as an additional text content block.

## Classifying a model with an agent

Start with `query_records(untagged=True)` and inspect each page using
`query_entity(uid=...)` and `screenshot(uids=[...])`. Learn the available
classes, predefined types and common property templates with `query_vocabulary`.
Its default response gives code counts; request `classification_system` for a
namespace's codes or `search` for a substring in code/title, with `offset` and
`limit` (default 200, maximum 1000).

Use `tag`, `set_record` and `add_classification` to classify batches of placements.
Each successful write is one undo step. Unknown uids fail before editing;
validation rejection returns `applied=false`, current records, and the
problems keyed by uid (only uids with messages appear; an empty map means
every target is valid). `force=true` on `set_record` permits invalid records.
Patches replace top-level fields (including whole lists and psets); a null patch
removes the record. Classification helpers preserve each object's other codes.
An omitted classification name uses the registry title, or the code itself when
no title is registered. An omitted tag name preserves the current record name.

Rows carry `linked=true` when the group comes from a linked file; `query_tree`
and `query_entity` report `linked` and `link_source` too. Those groups are
read-only for this document: the write tools refuse them, the exporter skips
them (see docs/ifc-export.md), and `query_records(linked=false)` hides them.

Read `query_records` again and inspect rows whose `problems` count is nonzero;
`query_record` gives the messages and resolved type defaults. Totals always cover
the entire model, regardless of filters; rows follow outliner order and `path`
contains ancestor names. Filters use stored records; name matches the outliner
name by case-insensitive substring. `schema` defaults to IFC4 (`validate_schema`
for `set_record`). Classification conveniences validate against IFC4.

Maintain types and systems with the registry tools. Delete operations return
referencing uids and `applied=false` unless forced. A forced deletion leaves those
references for later repair; the resulting registry must still pass its own
validator. `set_registry` is a validated whole-document replacement.
Use `query_changes` to see what the agent did, then have a human review the
classification in the BIM panel.

Finish with `export_ifc(path, profile=...)`. The result lists the elements
written, the records skipped with their validation messages, and, when the
profile names IDS files and `ifctester` is installed, the pass and fail counts
per specification. Fix the skipped records with `set_record` and export again:
GUIDs are persistent, so the second file describes the same objects.

Vocabulary entries additionally expose `domain` and the schema-specific
`type_class`. The response includes registry `tag_sets`; the default set's
classes come first. `set_tag_set(key, value)` and
`delete_tag_set(key, force=false)` use the same registry transaction path as type
edits. Tag sets are project choices, not object references.
