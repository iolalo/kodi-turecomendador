"""
Build script — genera los zips y addons.xml para el repositorio de Kodi.
Uso local:  python build.py
En CI:      mismo comando, output en ./dist/
"""
import hashlib
import os
import zipfile
import xml.etree.ElementTree as ET

ADDONS = [
    "plugin.video.turecomendador",
    "repository.turecomendador",
]
DIST = "dist"
EXCLUDE_EXTS = {".pyc", ".pyo"}
EXCLUDE_DIRS = {"__pycache__"}


def read_version(addon_id: str) -> str:
    tree = ET.parse(os.path.join(addon_id, "addon.xml"))
    return tree.getroot().get("version")


def make_zip(addon_id: str, version: str) -> str:
    out_dir = os.path.join(DIST, addon_id)
    os.makedirs(out_dir, exist_ok=True)
    zip_path = os.path.join(out_dir, f"{addon_id}-{version}.zip")

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(addon_id):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
            for fname in files:
                if any(fname.endswith(e) for e in EXCLUDE_EXTS):
                    continue
                filepath = os.path.join(root, fname)
                arcname = filepath.replace("\\", "/")
                zf.write(filepath, arcname)

    print(f"  OK {zip_path}")
    return zip_path


def build_addons_xml() -> str:
    root_el = ET.Element("addons")
    for addon_id in ADDONS:
        tree = ET.parse(os.path.join(addon_id, "addon.xml"))
        root_el.append(tree.getroot())

    ET.indent(root_el, space="  ")
    xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(
        root_el, encoding="unicode"
    )
    return xml_str


def make_index_html(directory: str, files: list[str]) -> None:
    links = "\n".join(f'<a href="{f}">{f}</a><br>' for f in sorted(files))
    html = f"<!DOCTYPE html><html><body>\n{links}\n</body></html>\n"
    with open(os.path.join(directory, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)


def main():
    os.makedirs(DIST, exist_ok=True)

    print("Generando zips...")
    addon_zips: dict[str, str] = {}
    for addon_id in ADDONS:
        version = read_version(addon_id)
        make_zip(addon_id, version)
        addon_zips[addon_id] = f"{addon_id}-{version}.zip"

    print("\nGenerando addons.xml...")
    xml_str = build_addons_xml()
    addons_xml_path = os.path.join(DIST, "addons.xml")
    with open(addons_xml_path, "w", encoding="utf-8") as f:
        f.write(xml_str)

    md5 = hashlib.md5(xml_str.encode("utf-8")).hexdigest()
    with open(os.path.join(DIST, "addons.xml.md5"), "w") as f:
        f.write(md5)

    print(f"  OK addons.xml  (md5: {md5})")

    print("\nGenerando index.html para Kodi...")
    # índice raíz
    root_entries = ["addons.xml", "addons.xml.md5"] + [f"{aid}/" for aid in ADDONS]
    make_index_html(DIST, root_entries)
    # índice por addon
    for addon_id, zip_name in addon_zips.items():
        make_index_html(os.path.join(DIST, addon_id), [zip_name])
    print("  OK index.html generados")

    print("\nBuild completo. Contenido de dist/:")
    for r, _, files in os.walk(DIST):
        for fname in files:
            path = os.path.join(r, fname).replace("\\", "/")
            print(f"  {path}")


if __name__ == "__main__":
    main()
