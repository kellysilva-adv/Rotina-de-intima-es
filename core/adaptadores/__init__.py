"""Adaptadores de captura por sistema processual."""

from core.adaptadores.base import AdaptadorBase, ResultadoVarredura
from core.adaptadores.datajud import AdaptadorDataJud
from core.adaptadores.mni import AdaptadorMNI
from core.adaptadores.html import (
    AdaptadorPJe,
    AdaptadorEproc,
    AdaptadorEsaj,
    AdaptadorProjudi,
)

ADAPTADORES_HTML = {
    "pje": AdaptadorPJe,
    "eproc": AdaptadorEproc,
    "esaj": AdaptadorEsaj,
    "projudi": AdaptadorProjudi,
}

__all__ = [
    "AdaptadorBase", "ResultadoVarredura", "AdaptadorMNI", "AdaptadorDataJud",
    "AdaptadorPJe", "AdaptadorEproc", "AdaptadorEsaj", "AdaptadorProjudi",
    "ADAPTADORES_HTML",
]
