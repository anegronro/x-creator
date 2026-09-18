"""Citas (quote posts) del titular del día que más conversación tiene.

En el algoritmo de X de 2026 citar pesa 5.0, igual que responder y diez veces
un like. La diferencia está en DÓNDE vive: un reply queda bajo el post de otro;
una cita sale en tu perfil y en el feed de tus seguidores, con el original
incrustado. Es tu post, no un comentario al margen.

X bloquea las citas por API igual que los replies (solo se puede citar lo que
te menciona). Hay un atajo conocido —publicar el texto con el enlace del post
al final, que X convierte en cita— y NO se usa: es rodear una restricción de
la plataforma, que es lo que cuesta cuentas. El sistema redacta; Angel pega.
"""

from __future__ import annotations

# Una al día. Es trabajo manual de Angel, y una cita a la semana buena vale más
# que siete del montón en su perfil.
CITAS_POR_DIA = 1
# Más allá de esto el post ya no está en juego: el algoritmo descarta a las 48h
# todo lo que tenga más de dos días, y a las 24 la conversación ya se enfrió.
HORAS_MAX_CITA = 24


def elegir_para_citar(posts, relevancia_de, excluir: set[str]):
    """El post con más conversación que tenga algo que aportarle.

    `posts` son `PostAjeno` con sus métricas. `relevancia_de(post)` devuelve
    la `Relevancia` del filtro de replies, así que las reglas de qué es
    "nuestro" son las mismas. `excluir` son los ids a los que ya se respondió o
    que ya se citaron: tocar dos veces el mismo post se lee como spam.

    Manda la conversación (replies + citas + reposts), no los likes: una cita
    se deja ver donde la gente está hablando.
    """
    from xcreator.publicar import edad_horas

    vivos = []
    for p in posts:
        if p.post_id in excluir:
            continue
        horas = edad_horas(p.post_id)
        if horas is not None and horas > HORAS_MAX_CITA:
            continue
        vivos.append(p)
    for p in sorted(vivos, key=lambda p: p.conversacion, reverse=True):
        rel = relevancia_de(p)
        if rel.aporta:
            return p, rel
    return None, None
