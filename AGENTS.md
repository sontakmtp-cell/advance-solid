Hãy dùng skill `mcp-builder` để thiết kế và xây dựng từ đầu một MCP server cho SolidWorks

Mục tiêu sản phẩm:
- Xây MCP server chạy qua stdio transport.
- Có một API thống nhất nhưng hỗ trợ 2 backend:
  1. Backend điều khiển SolidWorks trên Windows qua Python COM Automation API (`win32com.client` hoặc `comtypes`), có cơ chế bridge/IPC bổ sung cho các tác vụ cần chạy trong process SolidWorks.
  2. Backend headless để tạo, đọc, phân tích, biến đổi B-Rep cơ bản và export STEP/IGES/STL/3D-DXF offline mà không cần SolidWorks (dùng thư viện như CadQuery, OCP, hoặc pythonOCC).
- Hệ thống phải đủ tốt để một AI agent có thể dùng ngôn ngữ tự nhiên để thao tác mô hình 3D, bản vẽ 2D, và assembly trong SolidWorks.

Nguyên tắc capability:
- API chung phải có `backend_info` / `capabilities` để agent biết backend nào hỗ trợ thao tác nào.
- SolidWorks backend là backend đầy đủ cho document SLDPRT/SLDASM/SLDDRW, feature tree parametric, drawing, assembly mates, design table, Pack and Go, Routing.
- Headless backend không được giả vờ có parity với SolidWorks. Nó chỉ hỗ trợ các tác vụ CAD offline phù hợp với B-Rep/file exchange: import/export STEP/IGES/STL/DXF, tạo hình học cơ bản, boolean, fillet/chamfer cơ bản, mass/geometry analysis. Các thao tác như feature tree SolidWorks, mates, drawing SolidWorks, design table, Hole Wizard, Routing phải trả lỗi `unsupported` rõ ràng kèm gợi ý chuyển sang SolidWorks backend.

Yêu cầu bắt buộc cho backend SolidWorks:
- Phải thiết kế 2 đường điều khiển rõ ràng:
  - Primary path: Python MCP server -> COM Automation API -> SolidWorks.
  - Optional in-process path: Python MCP server -> IPC named pipe -> VBA/VSTA/.NET macro/add-in bridge -> SolidWorks API.
- Không gọi COM direct là "IPC tự thiết kế"; COM direct là đường điều khiển chính, IPC chỉ dùng cho macro/add-in bridge khi thật sự cần chạy in-process.
- Phải tạo COM dispatcher module (Python) để:
  - Kết nối / attach tới SolidWorks instance đang chạy.
  - Gửi lệnh qua COM API.
  - Chạy trong STA đúng cách (`CoInitialize`/`CoUninitialize`, message pump nếu cần).
  - Xử lý retry cho lỗi COM phổ biến như `RPC_E_CALL_REJECTED`, `RPC_E_SERVERFAULT`, server busy.
  - Có timeout/watchdog thực tế: timeout mềm cho từng operation, timeout cứng bằng worker process/thread boundary nếu cần; khi COM call treo không thể hủy sạch thì báo lỗi actionable và đề xuất restart/reattach backend.
  - Marshal kết quả từ COM objects về Python dict/JSON.
- Phải tạo VBA/VSTA macro bridge (tùy chọn, cho các tác vụ cần chạy in-process):
  - Ưu tiên VSTA/.NET add-in hoặc macro bridge ngắn hạn thay vì VBA loop blocking dài hạn trong UI thread.
  - Nếu dùng named pipe listener, phải có timeout, cancellation, non-blocking/polling hoặc chạy ngoài UI-critical path; không được để SolidWorks bị treo vì loop chờ pipe.
  - Bridge đọc JSON request, thực thi allowlist command trong SolidWorks, ghi JSON response.
  - Hỗ trợ execute_macro, get_custom_properties, set_custom_properties, traverse_feature_tree.
- Phải tạo helper module chuyên xử lý Custom Properties & BOM attributes, để hỗ trợ các tool liên quan tới metadata/BOM ổn định hơn.
- Phải tính tới các thao tác như:
  - execute macro / run COM command có allowlist, path sandbox, audit log, timeout, và mặc định bị giới hạn trong production
  - tạo/sửa feature (extrude, cut, fillet, chamfer, hole, pattern, v.v.)
  - insert component vào assembly, add mate
  - get/set custom properties
  - đọc BOM, mass properties, material
  - tạo drawing view, add dimension/annotation
  - các thao tác configuration/design table
- Cần mô tả rõ trách nhiệm từng thành phần:
  - MCP server (entry point, tool registration, stdio transport)
  - Backend abstraction (interface chung cho cả 2 backend)
  - COM dispatcher (kết nối + gọi SolidWorks COM API)
  - VBA/VSTA macro bridge (chạy in-process khi cần)
  - Custom Properties & BOM helper
  - IPC layer (named pipe là phương án chính cho macro/add-in bridge; shared memory chỉ dùng nếu có nhu cầu truyền payload lớn và phải có framing/locking rõ ràng)

Các nhóm chức năng cần có:

1. Quản lý document:
   - Tạo mới part/assembly/drawing.
   - Mở, lưu, lưu thành (Save As) với định dạng SLDPRT/SLDASM/SLDDRW/STEP/IGES/PDF/DXF/DWG/STL/3MF.
   - Đóng document, xem thông tin document (file path, units, material, mass).
   - Rebuild, force rebuild.
   - Undo/redo.
   - Đọc/ghi system options & document properties.

2. Quản lý Feature (Part modeling):
   - Tạo 2D sketch: line, circle, arc, rectangle, spline, polygon, slot, construction geometry.
   - Sketch constraints: coincident, concentric, tangent, parallel, perpendicular, equal, fix, dimension.
   - Tạo 3D feature: Extrude Boss/Cut, Revolve Boss/Cut, Sweep, Loft, Fillet, Chamfer, Shell, Draft, Rib, Hole Wizard, Linear/Circular Pattern, Mirror.
   - Reference geometry: plane, axis, coordinate system.
   - Liệt kê feature tree, xem chi tiết feature, suppress/unsuppress, rollback, edit feature, delete feature.

3. Quản lý Assembly:
   - Insert component (part hoặc sub-assembly).
   - Add mate: coincident, concentric, distance, angle, tangent, lock, gear, cam, width, path mate.
   - Move/rotate component.
   - Liệt kê component tree, đếm components.
   - Suppress/unsuppress component.
   - Component patterns.
   - Interference detection, collision detection.
   - Exploded view: tạo, cấu hình, collapse.

4. Quản lý Drawing:
   - Tạo drawing từ part/assembly.
   - Insert view: model view, projected view, section view, detail view, broken-out section, auxiliary view.
   - Thêm dimension: smart dimension, ordinate, chamfer, hole callout.
   - Thêm annotation: note, balloon, surface finish, weld symbol, GD&T (geometric tolerance), datum.
   - Bill of Materials (BOM): insert, configure columns, update.
   - Title block: đọc/ghi thông tin.
   - Sheet management: thêm/xóa/đổi sheet, set sheet format.

5. Custom Properties & BOM:
   - Đọc/ghi custom properties ở cấp file, configuration, cut-list.
   - Đọc BOM từ assembly.
   - Đọc mass properties (khối lượng, thể tích, trọng tâm, moment of inertia).
   - Đọc/set material.
   - Configuration management: tạo, xóa, activate, đổi tên configuration.

6. Quản lý Appearance & Display:
   - Set material appearance/color cho body, face, feature, component.
   - Show/hide component/body.
   - Section view (hiển thị cắt).
   - Tạo named view, zoom to fit, zoom to entity.
   - Chụp screenshot/render viewport.

7. Import/Export & File operations:
   - Import: STEP, IGES, Parasolid, DXF/DWG, STL.
   - Export: STEP, IGES, Parasolid, PDF, DXF/DWG, STL, 3MF, eDrawings.
   - Pack and Go.
   - Batch export.

8. System tools:
   - Kiểm tra status kết nối SolidWorks.
   - Health check (SolidWorks version, API version, license).
   - Backend info, runtime info.
   - Init / attach to SolidWorks instance.
   - Execute macro (VBA hoặc VSTA).
   - Đọc/ghi system options.

9. Semantic CAD tools:
   - Phân tích hình học 3D (bounding box, surface area, volume).
   - Phát hiện feature từ geometry (holes, pockets, bosses, fillets, chamfers, patterns, symmetry).
   - Đề xuất manufacturing method dựa trên geometry analysis.
   - Sinh dimension plan cho drawing.
   - Chấm điểm layout dimension.
   - Apply/validate dimension plan.
   - Design rule check (wall thickness, draft angle, undercut detection).
   - DFM (Design for Manufacturability) analysis cơ bản.

10. P&ID / Piping helpers (nếu dùng SolidWorks Routing):
    - Tạo route, insert fitting, valve, instrument.
    - Pipe spec management.
    - Generate isometric drawing.
    - BOM cho piping.

Lưu ý scope:
- Các nhóm chức năng trên là product roadmap. Không bắt buộc implement toàn bộ đầy đủ trong MVP đầu tiên.
- MVP bắt buộc phải có: stdio MCP server, backend abstraction, config/logging/error formatting, SolidWorks attach/status/health, document open/save/info/rebuild/export cơ bản, custom properties, mass/material info, headless import/analyze/export cơ bản, tests smoke, README, MCP client config.
- Phase 2: sketch/feature cơ bản, assembly component/mate cơ bản, drawing/view/dimension/annotation cơ bản.
- Phase 3: semantic CAD, DFM, Routing/Piping, advanced drawing/BOM/layout validation.
- Routing/Piping phụ thuộc license/add-in SolidWorks Routing; implement dạng optional module và trả `unsupported` nếu môi trường không có capability.

Yêu cầu kỹ thuật:
- Thiết kế theo tư duy agent-centric, không chỉ bọc API thấp cấp.
- Tool phải phục vụ workflow hoàn chỉnh, dễ dùng cho LLM.
- Input schema phải rõ ràng, validation chặt chẽ.
- Output phải ngắn gọn, giàu tín hiệu, có thể cấu hình mức chi tiết.
- Error messages phải actionable và hướng agent tới bước tiếp theo.
- Tổ chức mã nguồn tốt, có abstraction cho backend, shared utilities, formatting, timeout handling, logging, config bằng environment variables.
- Ưu tiên Python cho MCP server, dùng `win32com.client` hoặc `comtypes` cho COM bridge, VBA/VSTA cho macro bridge khi cần chạy in-process SolidWorks.
- Thiết kế để có thể chạy production và mở rộng sau này.
- Xử lý COM threading đúng cách (CoInitialize, STA/MTA, message pump nếu cần).
- Mọi tool có side effect phải khai báo rõ destructive/idempotent/open-world hint nếu SDK hỗ trợ, validate input chặt, và trả error message hướng agent tới bước tiếp theo.
- Mọi thao tác file phải dùng allowlist workspace/root paths từ environment variables; không cho macro/tool tùy ý truy cập toàn bộ filesystem nếu không cấu hình rõ.

Quy trình bắt buộc:
1. Nghiên cứu domain SolidWorks API và đề xuất kiến trúc tổng thể cho một SolidWorks MCP server hiện đại.
2. Xác định danh sách tool tối ưu cho AI agent.
3. Thiết kế cơ chế COM bridge + macro bridge, bao gồm COM dispatcher và VBA/VSTA macro bridge.
4. Lập implementation plan chi tiết.
5. Tạo project từ đầu trong workspace hiện tại.
6. Implement MVP trước: MCP server, schemas, backend abstraction, COM dispatcher, macro bridge scaffold an toàn, headless backend cơ bản, helper custom properties/BOM, smoke tests, evaluation read-only, và tài liệu sử dụng.
7. Kiểm tra build/test ở mức hợp lý.
8. Tổng kết phần đã làm, assumption, hạn chế hiện tại, và hướng mở rộng.

Cách làm việc:
- Không hỏi lại những câu quá cơ bản nếu có thể tự quyết định hợp lý.
- Nếu phải giả định, hãy nêu rõ assumption.
- Chủ động thực hiện end-to-end, không chỉ dừng ở mức bản thiết kế.
- Sau khi hoàn thành, cung cấp:
  - sơ đồ kiến trúc,
  - danh sách tool đã xây,
  - cấu trúc thư mục,
  - mô tả luồng điều khiển: Python MCP server <-> COM API <-> SolidWorks, và Python <-> Named Pipe <-> VBA/VSTA/.NET bridge <-> SolidWorks,
  - mô tả vai trò COM dispatcher, macro bridge, và custom properties helper,
  - hướng dẫn chạy local,
  - ví dụ cấu hình MCP client,
  - các rủi ro kỹ thuật còn lại.

Hãy chia việc thành các subagent để triển khai song song theo từng module rõ ràng.
Trước khi giao subagent:
- Main agent phải tạo trước kiến trúc thư mục, backend interface, schema boundary và ownership map.
- Shared config, shared schema, core interface chỉ do main agent tạo/sửa.
- Subagent chỉ implement module riêng dựa trên interface và schema đã được main agent chốt.
- Nếu cần đổi interface/schema, subagent chỉ đề xuất, không tự sửa.
- SolidWorks COM bridge subagent chỉ xử lý backend + COM/macro bridge.
- MCP tools subagent chỉ xử lý tool registration, docs/test và mapping schema đã có vào MCP tools; nếu cần schema mới hoặc đổi schema, chỉ ghi đề xuất cho main agent.
- Sau implementation, tạo thêm tối thiểu 3-5 evaluation read-only smoke cơ bản để kiểm tra MCP server có dùng được bởi AI agent; nếu còn thời gian, mở rộng thành 10 evaluation workflow theo hướng dẫn `mcp-builder`.

Tác nhân chính:
- Giữ kiến trúc tổng thể.
- Chia việc, theo dõi tiến độ, review kết quả.
- Không để nhiều subagent sửa cùng một file lõi cùng lúc.
- Sau cùng hợp nhất code, kiểm tra build/test và viết tổng kết.

Ownership map bắt buộc:
- Main agent sở hữu và chỉ main agent được sửa: `pyproject.toml`, `README.md` khung ban đầu, `src/*/config.py`, `src/*/core/backend.py`, `src/*/core/errors.py`, `src/*/schemas/`, project layout, CI/test harness khung.
- SolidWorks COM Bridge + IPC subagent sở hữu: `src/*/backends/solidworks/`, `src/*/bridges/solidworks_macro/`, macro/add-in sample files, tests riêng cho dispatcher bằng mocks.
- Custom Properties + BOM subagent sở hữu: `src/*/helpers/properties.py`, `src/*/helpers/bom.py`, `src/*/helpers/materials.py`, `src/*/helpers/configurations.py`, tests helper bằng mocks/fixtures.
- Headless 3D Backend subagent sở hữu: `src/*/backends/headless/`, geometry import/export/analyze tests.
- MCP Tools + Docs/Test subagent sở hữu: `src/*/server.py`, `src/*/tools/`, docs usage/config, evaluation files, tests tool registration/mapping. Không sửa `schemas` hoặc `core` nếu chưa được main agent chấp thuận.
- Drawing & Annotation subagent sở hữu: `src/*/domain/drawing.py` hoặc `src/*/backends/solidworks/drawing.py` theo layout main agent tạo, drawing fixtures/tests riêng. Không sửa tool registration trừ khi được giao rõ.

Tạo các subagent sau:

1. SolidWorks COM Bridge + IPC
- Thiết kế COM dispatcher kết nối SolidWorks qua `win32com.client` / `comtypes`.
- Xử lý COM threading (CoInitialize, STA), message pump nếu cần, timeout mềm/cứng, retry, error handling cho các lỗi COM phổ biến.
- Implement execute_macro, run_com_command dạng an toàn: allowlist command, timeout, audit log, structured error, không expose arbitrary code execution mặc định.
- Tạo VBA/VSTA/.NET macro bridge scaffold qua named pipe cho các tác vụ cần chạy in-process; listener không được blocking vô hạn trong UI thread.
- Implement các bridge cho feature/component/view thông qua COM API.

2. Custom Properties + BOM Tools
- Tạo helper module chuyên xử lý Custom Properties (file-level, configuration-level, cut-list-level).
- Implement get/set custom properties, read BOM, mass properties, material management.
- Implement configuration management: tạo, xóa, activate, đổi tên.
- Đảm bảo thao tác metadata ổn định và dễ dùng cho AI agent.

3. Headless 3D Backend
- Implement backend offline đọc/tạo/phân tích/biến đổi B-Rep cơ bản từ STEP/IGES không cần SolidWorks (dùng CadQuery / pythonOCC / OCP).
- Hỗ trợ tạo sketch, extrude, fillet, chamfer, boolean operations cơ bản.
- Hỗ trợ đọc geometry, mass properties, export STEP/STL.
- Giữ API tương thích ở mức interface chung, nhưng phải trả `unsupported` rõ ràng cho capability chỉ SolidWorks mới có.

4. MCP Tools + Docs/Test
- Dùng shared schema do main agent tạo; đề xuất bổ sung nếu thiếu, không tự sửa shared schema/core interface.
- Implement tool registration và mapping cho các nhóm: document, feature, assembly, drawing, custom properties/BOM, appearance, import/export, system, semantic CAD, routing/piping.
- Không implement business logic backend trong tool layer; tool layer chỉ validate schema, gọi backend/helper, format response/error.
- Viết README, ví dụ config MCP client, test cơ bản.

5. Drawing & Annotation Tools
- Implement tạo drawing từ part/assembly.
- Insert các loại view (model, projected, section, detail, auxiliary).
- Thêm dimensions (smart, ordinate, chamfer, hole callout).
- Thêm annotations (note, balloon, surface finish, weld symbol, GD&T, datum).
- BOM insertion và title block management.
- Không sửa MCP tool registration hoặc shared schema nếu chưa được main agent giao; nếu cần field/schema mới thì ghi đề xuất.

Quy tắc cho mọi subagent:
- Chỉ chỉnh sửa module được giao.
- Tuân theo kiến trúc chung.
- Không tự ý đổi shared config, shared schema hoặc core interface nếu chưa được main agent đồng ý.
- Chỉ trả về danh sách file đã sửa, nội dung thay đổi chính, assumption và lỗi còn lại.
