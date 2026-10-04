"""¿Sigue la cuenta penalizada? Se mide por el alcance, no por la etiqueta.

X etiquetó la cuenta el 2026-10-03 por manipulación de plataforma y no
expone esa etiqueta por API: no hay campo que preguntar. Lo que sí se ve es
su efecto, y es brutal. Los posts de ese día hicieron 0 y 1 impresiones,
cuando la mediana de los días anteriores andaba entre 30 y 60.

Así que esto vigila lo único observable: la mediana de impresiones de los
últimos posts propios. Cuando vuelve a niveles normales, la penalización se
levantó. Es un indicio, no la etiqueta: X avisa en la app, y esa es la
confirmación de verdad.

Cuesta $0.005 por post leído, así que una pasada diaria de 10 posts son 5
centavos y $1.50 al mes.
"""

from __future__ import annotations

import statistics as st
from dataclasses import dataclass

# Cuántos posts recientes se miran y cuántos hacen falta para opinar.
POSTS = 10
MINIMO = 4

# La mediana a partir de la cual se considera que la cuenta volvió. Está muy
# por debajo de lo normal de la cuenta (30 a 60) a propósito: avisar de más
# es barato, no avisar cuando ya se puede publicar cuesta días.
UMBRAL_RECUPERADA = 15
# Y por debajo de esto, la penalización sigue puesta sin duda.
UMBRAL_PENALIZADA = 5


@dataclass
class Lectura:
    posts: int
    mediana: float
    maximo: int

    @property
    def recuperada(self) -> bool:
        return self.posts >= MINIMO and self.mediana >= UMBRAL_RECUPERADA

    @property
    def penalizada(self) -> bool:
        return self.posts >= MINIMO and self.mediana <= UMBRAL_PENALIZADA

    def resumen(self) -> str:
        if self.posts < MINIMO:
            return (f"Solo {self.posts} posts recientes: hacen falta {MINIMO} "
                    f"para decir nada. Publica algo a mano y vuelvo a mirar.")
        estado = ("la cuenta parece RECUPERADA" if self.recuperada
                  else "la cuenta SIGUE penalizada" if self.penalizada
                  else "zona gris: ni recuperada ni plana del todo")
        return (f"{estado}. Mediana de impresiones de los últimos "
                f"{self.posts} posts: {self.mediana:.0f} (máximo {self.maximo}).")


def leer(impresiones: list[int]) -> Lectura:
    """La lectura a partir de las impresiones de los últimos posts."""
    if not impresiones:
        return Lectura(0, 0.0, 0)
    return Lectura(len(impresiones), float(st.median(impresiones)),
                   max(impresiones))


def impresiones_recientes(cliente, handle: str, limite: int = POSTS) -> list[int]:
    """Las impresiones de los últimos posts propios, sin contar replies.

    Un reply cuelga de la conversación de otro y su alcance dice más de esa
    cuenta que de la nuestra: mezclarlos tapa justo lo que se quiere ver.
    """
    out = []
    for p in cliente.posts_recientes(handle, limite=limite):
        texto = (p.texto or "").lstrip()
        if texto.startswith("@") or texto.startswith("RT "):
            continue
        imp = (p.metricas or {}).get("impression_count")
        if imp is not None:
            out.append(int(imp))
    return out
