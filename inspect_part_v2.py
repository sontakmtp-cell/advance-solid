"""Deep-inspect the active SolidWorks part – raw COM exploration."""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

os.environ.setdefault("SOLIDWORKS_MCP_BACKEND", "solidworks")
os.environ.setdefault("SOLIDWORKS_MCP_WORKSPACE_ROOTS", "H:\\MCP-AutoCAD;H:\\CAD-Work;C:\\;D:\\;E:\\;F:\\;G:\\;H:\\")


def pp(label, data):
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    if isinstance(data, str):
        print(data)
    else:
        print(json.dumps(data, indent=2, ensure_ascii=False, default=str))


async def main():
    from solidworks_mcp.config import load_settings
    from solidworks_mcp.backends.solidworks.dispatcher import SolidWorksComDispatcher

    settings = load_settings()
    dispatcher = SolidWorksComDispatcher(settings)

    # Attach
    info = dispatcher.attach(create_if_missing=False)
    pp("ATTACH", info)

    def _deep_inspect(sw):
        result = {}
        
        # ActiveDoc
        doc = sw.ActiveDoc
        if doc is None:
            result["active_doc"] = None
            # Try to get documents list
            try:
                first_doc = sw.GetFirstDocument()
                if first_doc:
                    result["first_document"] = {
                        "title": _safe(first_doc, "GetTitle"),
                        "path": _safe(first_doc, "GetPathName"),
                        "type": _safe(first_doc, "GetType"),
                    }
            except Exception as e:
                result["first_doc_error"] = str(e)
            return result

        result["title"] = _safe(doc, "GetTitle")
        result["path"] = _safe(doc, "GetPathName")
        result["type"] = _safe(doc, "GetType")
        result["type_name"] = {1: "Part", 2: "Assembly", 3: "Drawing"}.get(_safe(doc, "GetType"), "Unknown")
        
        # Configurations
        config_names = _safe(doc, "GetConfigurationNames")
        result["configurations"] = list(config_names) if config_names else []
        
        active_config = _safe(doc, "GetActiveConfiguration")
        result["active_config_name"] = _safe(active_config, "Name") if active_config else None

        # Extension
        ext = None
        try:
            ext = doc.Extension
        except Exception:
            pass
        result["has_extension"] = ext is not None
        
        # Custom property manager
        if ext:
            try:
                cpm = ext.CustomPropertyManager("")
                names = cpm.GetNames()
                props = {}
                if names:
                    for name in names:
                        val = ""
                        resolved = ""
                        was_resolved = False
                        try:
                            r = cpm.Get5(name, False, val, resolved, was_resolved)
                            props[name] = {"raw_result": str(r)}
                        except Exception as e:
                            try:
                                props[name] = {"get_value": cpm.Get(name)}
                            except Exception:
                                props[name] = {"error": str(e)}
                result["custom_properties_file"] = props
                result["custom_property_count"] = len(names) if names else 0
            except Exception as e:
                result["custom_properties_error"] = str(e)
        
        # Feature tree - full traverse
        features = []
        try:
            feat = doc.FirstFeature()
        except Exception:
            try:
                feat = doc.FirstFeature
            except Exception:
                feat = None
        while feat is not None and len(features) < 200:
            feat_info = {
                "name": _safe(feat, "Name"),
                "type": _safe(feat, "GetTypeName2") or _safe(feat, "GetTypeName"),
                "suppressed": _safe(feat, "IsSuppressed"),
            }
            # Sub-features
            try:
                sub = feat.GetFirstSubFeature()
                if sub:
                    subs = []
                    while sub and len(subs) < 20:
                        subs.append({
                            "name": _safe(sub, "Name"),
                            "type": _safe(sub, "GetTypeName2") or _safe(sub, "GetTypeName"),
                        })
                        try:
                            sub = sub.GetNextSubFeature()
                        except Exception:
                            sub = None
                    feat_info["sub_features"] = subs
            except Exception:
                pass
            features.append(feat_info)
            try:
                feat = feat.GetNextFeature()
            except Exception:
                try:
                    feat = feat.GetNextFeature
                except Exception:
                    feat = None
        result["features"] = features
        result["feature_count"] = len(features)
        
        # Bodies
        try:
            bodies = doc.GetBodies2(0, False)  # 0 = swSolidBody
            if bodies:
                body_info = []
                for body in bodies:
                    bi = {"name": _safe(body, "Name")}
                    try:
                        faces = body.GetFaces()
                        bi["face_count"] = len(faces) if faces else 0
                    except Exception:
                        bi["face_count"] = "unknown"
                    try:
                        edges = body.GetEdges()
                        bi["edge_count"] = len(edges) if edges else 0
                    except Exception:
                        bi["edge_count"] = "unknown"
                    body_info.append(bi)
                result["solid_bodies"] = body_info
                result["solid_body_count"] = len(body_info)
            else:
                result["solid_bodies"] = []
                result["solid_body_count"] = 0
        except Exception as e:
            result["bodies_error"] = str(e)
        
        # Mass properties
        try:
            mass_props = doc.Extension.CreateMassProperty()
            if mass_props:
                result["mass_properties"] = {
                    "mass_kg": _safe(mass_props, "Mass"),
                    "volume_m3": _safe(mass_props, "Volume"),
                    "surface_area_m2": _safe(mass_props, "SurfaceArea"),
                    "center_of_mass": _safe(mass_props, "CenterOfMass"),
                    "density": _safe(mass_props, "Density"),
                }
            else:
                raw = doc.GetMassProperties()
                result["mass_properties_raw"] = list(raw) if raw else None
        except Exception as e:
            result["mass_properties_error"] = str(e)
        
        # Material
        try:
            config_name = _safe(active_config, "Name") if active_config else ""
            mat = doc.GetMaterialPropertyName2(config_name or "", "")
            result["material"] = mat
        except Exception as e:
            result["material_error"] = str(e)
        
        # Units
        try:
            unit_sys = doc.GetUserPreferenceIntegerValue(0)
            unit_map = {0: "MKS (m, kg, s)", 1: "CGS (cm, g, s)", 2: "MMGS (mm, g, s)", 
                       3: "IPS (inch, lbm, s)", 4: "Custom"}
            result["unit_system"] = unit_map.get(unit_sys, f"Unknown ({unit_sys})")
        except Exception:
            result["unit_system"] = "unknown"

        # Bounding box
        try:
            bb = doc.GetPartBox()
            if bb:
                result["bounding_box"] = {
                    "min": [bb[0], bb[1], bb[2]],
                    "max": [bb[3], bb[4], bb[5]],
                    "size": [bb[3]-bb[0], bb[4]-bb[1], bb[5]-bb[2]],
                }
        except Exception:
            pass
        
        return result

    result = dispatcher.call("deep_inspect", _deep_inspect)
    pp("DEEP INSPECTION RESULT", result)


def _safe(obj, method, *args):
    if obj is None:
        return None
    try:
        candidate = getattr(obj, method)
        return candidate(*args) if callable(candidate) else candidate
    except Exception:
        return None


if __name__ == "__main__":
    asyncio.run(main())
