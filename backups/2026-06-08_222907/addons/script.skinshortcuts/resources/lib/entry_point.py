# -*- coding: utf-8 -*-
import sys, os
_ADDONS = "/storage/.kodi/addons"
for _m in ["script.module.unidecode","script.module.simpleeval","script.module.six"]:
    _p = os.path.join(_ADDONS, _m, "lib")
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

from skinshorcuts import skinshortcuts
from skinshorcuts.common import log
from skinshorcuts.constants import ADDON_VERSION

log("script version %s started" % ADDON_VERSION)
script = skinshortcuts.Script()
script.route()
log("script stopped")
