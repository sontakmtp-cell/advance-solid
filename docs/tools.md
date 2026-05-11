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

## Side Effects

Read-only tools advertise read-only annotations. Tools that may mutate files, models, SolidWorks session state, or backend state advertise non-read-only annotations. Destructive roadmap operations such as configuration deletion are marked as destructive at the grouped-tool level because the exact action is supplied at runtime.
