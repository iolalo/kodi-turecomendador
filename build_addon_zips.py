"""
Creates addon ZIPs for all addons we need to install on the Pi,
matching the format Kodi uses: addonid-version.zip
"""
import os, zipfile, xml.etree.ElementTree as ET
from pathlib import Path

NOTEBOOK_ADDONS = Path(os.environ["APPDATA"]) / "Kodi" / "addons"
OUT_DIR = Path(r"C:\Users\ralej\OneDrive\Kodi-dev\dist\addon_zips")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Addons to package (those we copied but Kodi didn't detect)
TO_PACK = [
    "plugin.video.themoviedb.helper",
    "resource.images.weathericons.white",
    "resource.language.es_ar",
    "script.common.plugin.cache",
    "script.embuary.info",
    "script.favourites",
    "script.globalsearch",
    "script.image.resource.select",
    "script.module.addon.signals",
    "script.module.arrow",
    "script.module.beautifulsoup4",
    "script.module.certifi",
    "script.module.chardet",
    "script.module.dateutil",
    "script.module.future",
    "script.module.html2text",
    "script.module.html5lib",
    "script.module.idna",
    "script.module.infotagger",
    "script.module.jurialmunkey",
    "script.module.kodi-six",
    "script.module.requests",
    "script.module.routing",
    "script.module.simple-requests",
    "script.module.simplecache",
    "script.module.simpleeval",
    "script.module.simpleplugin3",
    "script.module.six",
    "script.module.soupsieve",
    "script.module.trakt",
    "script.module.typing_extensions",
    "script.module.unidecode",
    "script.module.urllib3",
    "script.module.webencodings",
    "script.rss.editor",
    "script.trakt",
    "service.autosubs",
    "service.subtitles.a4ksubtitles",
    "service.subtitles.opensubtitles",
    "service.subtitles.opensubtitles-com",
    "service.subtitles.rvm.addic7ed",
    "service.subtitles.subdivx",
    "service.subtitles.subsceneplus",
    "weather.gismeteo",
]

errors = []
for addon_name in TO_PACK:
    src = NOTEBOOK_ADDONS / addon_name
    if not src.exists():
        print(f"SKIP {addon_name} - not found in notebook")
        continue

    xml_path = src / "addon.xml"
    if not xml_path.exists():
        print(f"SKIP {addon_name} - no addon.xml")
        continue

    tree = ET.parse(xml_path)
    version = tree.getroot().get("version", "0.0.1")
    zip_name = f"{addon_name}-{version}.zip"
    zip_path = OUT_DIR / zip_name

    print(f"Packing {zip_name}...", end=" ", flush=True)
    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for file in src.rglob("*"):
                if file.is_file():
                    arcname = addon_name + "/" + str(file.relative_to(src))
                    zf.write(file, arcname)
        print("OK")
    except Exception as e:
        print(f"ERROR: {e}")
        errors.append((addon_name, str(e)))

print(f"\nDone. ZIPs in: {OUT_DIR}")
if errors:
    print("Errors:", errors)
