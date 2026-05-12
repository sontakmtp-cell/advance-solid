# Tool Mapping Notes

The MCP tool layer is intentionally thin. It validates shared Pydantic schemas, selects the backend, invokes backend/helper/domain methods, and formats success or actionable error responses.

## Direct MVP Mappings

`system_backend_info` -> `backend.backend_info()`

`system_capabilities` -> `backend.capabilities()`

`system_health` -> `backend.health()`

`system_attach` -> `backend.attach()`

`system_execute_macro` -> `backend.execute_macro(macro_path, procedure, module)`

`system_run_com_command` -> `backend.run_com_command(command, args)`

`document_open` -> `backend.open_document(path, document_type)`

`document_save` -> `backend.save_document(path)`

`document_info` -> `backend.document_info(path, detail)`

`document_rebuild` -> `backend.rebuild(force)`

`document_export` -> `backend.export_document(path, format, options)`

`custom_properties_get` -> `backend.get_custom_properties(scope, configuration)`

`custom_properties_set` -> `backend.set_custom_properties(properties, scope, configuration)`

`mass_properties` -> `backend.mass_properties()`

`material_info` -> `backend.material_info(material)`

`part_inspect` -> `backend.inspect_part(...)`

## Optional Backend Mappings

These tools call a same-named backend workflow method when present. Otherwise they return `unsupported`.

`bom_read` -> `backend.read_bom(source)`

`configurations` -> `backend.configurations(action, name, new_name)`

`feature_operation` -> `backend.feature_operation(operation, parameters)`

`assembly_operation` -> `backend.assembly_operation(operation, parameters)`

`drawing_operation` -> `backend.drawing_operation(operation, parameters)`

`appearance_operation` -> `backend.appearance_operation(operation, parameters)`

`import_export_operation` -> `backend.import_export_operation(operation, parameters)`

`semantic_analysis` -> `backend.semantic_analysis(analysis, detail, parameters)`

`routing_operation` -> `backend.routing_operation(operation, parameters)`

## Phase 3 Operation Catalog

Phase 3 adds semantic CAD and review-oriented workflows. These tools return heuristic,
high-signal results by default and should not be treated as release-grade engineering
approval without SolidWorks-side verification.

### `semantic_analysis`

Supported analysis names:

`geometry`, `feature_recognition`, `manufacturing_method`, `dimension_plan`,
`dimension_layout_score`, `design_rule_check`, `dfm`.

Example parameter shapes:

```json
{"analysis": "dfm", "parameters": {"min_wall_thickness": 1.5}}
```

```json
{"analysis": "dimension_layout_score", "parameters": {"dimensions": [{"id": "D1", "x": 0.1, "y": 0.1, "width": 0.2, "height": 0.05}]}}
```

The SolidWorks backend derives signals from read-only part inspection. The headless
backend derives signals from B-Rep counts, bounding boxes, and operation metadata.

### `routing_operation`

Supported operation names:

`create_route`, `insert_fitting`, `pipe_spec`, `isometric_drawing`, `piping_bom`.

Routing/Piping is optional and requires the SolidWorks Routing add-in/license. Backends
that cannot verify that environment return `unsupported` with a next step instead of
pretending to support the workflow.

## Phase 2 Operation Catalog

Grouped Phase 2 tools use a stable `{operation, parameters}` envelope. The tool layer validates the operation name and delegates the parameter object to the selected backend. Backends may return `unsupported` for operations they cannot perform.

### `feature_operation`

Supported operation names:

`create_sketch`, `extrude_boss`, `extrude_cut`, `revolve`, `fillet`, `chamfer`, `hole`, `pattern`, `mirror`, `list_tree`, `suppress`, `unsuppress`, `delete`.

Example parameter shapes:

```json
{"operation": "list_tree", "parameters": {"include_suppressed": true, "max_depth": 4}}
```

```json
{"operation": "extrude_boss", "parameters": {"sketch": "Sketch1", "depth": 0.025, "direction": "blind", "name": "Boss-Extrude1"}}
```

```json
{"operation": "fillet", "parameters": {"selection": {"edges": ["Edge1", "Edge2"]}, "radius": 0.003}}
```

### `assembly_operation`

Supported operation names:

`insert_component`, `add_mate`, `move_component`, `rotate_component`, `list_components`, `suppress_component`, `unsuppress_component`, `interference_detection`, `exploded_view`.

Example parameter shapes:

```json
{"operation": "list_components", "parameters": {"include_suppressed": false, "recursive": true}}
```

```json
{"operation": "add_mate", "parameters": {"mate_type": "concentric", "entities": ["PartA/Axis1", "PartB/Hole1"], "alignment": "aligned"}}
```

```json
{"operation": "interference_detection", "parameters": {"include_multibody": true, "treat_coincidence_as_interference": false}}
```

### `drawing_operation`

Supported operation names:

`create_from_model`, `insert_view`, `add_dimension`, `add_annotation`, `insert_bom`, `validate_layout`, `title_block`, `sheet_management`.

Example parameter shapes:

```json
{"operation": "insert_view", "parameters": {"model_path": "H:\\\\CAD-Work\\\\bracket.SLDPRT", "view": "front", "x": 0.12, "y": 0.18, "scale": "1:2"}}
```

```json
{"operation": "add_dimension", "parameters": {"dimension_type": "smart", "entities": ["Edge1", "Edge2"], "placement": {"x": 0.15, "y": 0.22}}}
```

```json
{"operation": "add_annotation", "parameters": {"annotation_type": "note", "text": "REMOVE BURRS", "x": 0.18, "y": 0.05}}
```

```json
{"operation": "validate_layout", "parameters": {"sheet": {"width": 1.0, "height": 0.7}, "dimensions": [{"id": "D1", "x": 0.1, "y": 0.1, "width": 0.2, "height": 0.05}]}}
```

### `appearance_operation`

Supported operation names:

`set_color`, `show_hide`, `section_view`, `named_view`, `zoom`, `screenshot`.

Example parameter shapes:

```json
{"operation": "named_view", "parameters": {"name": "isometric", "activate": true}}
```

```json
{"operation": "show_hide", "parameters": {"target": "component", "name": "Bracket-1", "visible": false}}
```

```json
{"operation": "screenshot", "parameters": {"path": "H:\\\\MCP-AutoCAD\\\\out\\\\viewport.png", "width": 1600, "height": 1000}}
```

### `import_export_operation`

Supported operation names:

`import`, `export`, `pack_and_go`, `batch_export`.

Prefer `document_open` for single-file import and `document_export` for single active-document export. Use this grouped tool for workflow-level operations such as Pack and Go or batch export.

Example parameter shapes:

```json
{"operation": "pack_and_go", "parameters": {"destination": "H:\\\\CAD-Work\\\\pkg", "include_drawings": true, "flatten": false}}
```

```json
{"operation": "batch_export", "parameters": {"source_glob": "H:\\\\CAD-Work\\\\*.SLDPRT", "format": "step", "destination": "H:\\\\CAD-Work\\\\exchange"}}
```

## Side Effects

Read-only tools advertise read-only annotations. Tools that may mutate files, models, SolidWorks session state, or backend state advertise non-read-only annotations. Destructive roadmap operations such as configuration deletion are marked as destructive at the grouped-tool level because the exact action is supplied at runtime.

## SolidWorks Part Inspection

`part_inspect` integrates the former `inspect_part_v2.py` workflow as a read-only MCP tool. It is intended for quick agent situational awareness on the active SolidWorks part: document identity, configurations, custom properties, feature/subfeature tree, body counts, mass properties, material, unit system, and bounding box. It is SolidWorks-backend only; headless backends return `unsupported`.
