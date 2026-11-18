"""
Protocolo de texto que usa el cliente para hablar con servidor.py.

El servidor solo entiende tres tipos de mensaje:
  <name>TEXTO      -> guarda TEXTO como el nombre del cliente
  <command>TEXTO   -> lo reenvía tal cual a los demás clientes
  cualquier otro   -> lo reenvía como "<nombre> mensaje"

Para mandar el avatar sin modificar el servidor, el cliente guarda
su nombre como "Nombre|07" (nombre + número de avatar). Así, cada
mensaje que reenvía el servidor llega como "<Nombre|07> hola".
"""

import re

SEPARADOR = "|"
AVATAR_DEFAULT = 0  # 0 = sin avatar (por ejemplo, alguien conectado con nc)

_RE_MENSAJE = re.compile(r"^<(.*?)> (.*)$", re.DOTALL)


def armar_nombre(nombre: str, avatar: int) -> str:
    """Mensaje para registrar nombre y avatar en el servidor."""
    nombre = nombre.replace(SEPARADOR, "").replace("<", "").replace(">", "").strip()
    return f"<name>{nombre}{SEPARADOR}{avatar:02d}"


def armar_aviso_entrada(nombre: str, avatar: int) -> str:
    """Comando para avisar a los demás que alguien entró al chat."""
    return f"<command>join{SEPARADOR}{nombre}{SEPARADOR}{avatar:02d}"


def separar_nombre(etiqueta: str):
    """'Abraham|07' -> ('Abraham', 7). Si no trae avatar -> (etiqueta, 0)."""
    if SEPARADOR in etiqueta:
        nombre, _, num = etiqueta.rpartition(SEPARADOR)
        if num.isdigit():
            return nombre, int(num)
    return etiqueta, AVATAR_DEFAULT


def interpretar(linea: str) -> dict:
    """
    Convierte una línea recibida del servidor en un diccionario:
      {"tipo": "mensaje", "nombre", "avatar", "texto"}
      {"tipo": "entrada", "nombre", "avatar"}
      {"tipo": "sistema", "texto"}
    """
    if linea.startswith("<command>"):
        partes = linea[len("<command>"):].split(SEPARADOR)
        if len(partes) == 3 and partes[0] == "join" and partes[2].isdigit():
            return {"tipo": "entrada", "nombre": partes[1], "avatar": int(partes[2])}
        return {"tipo": "sistema", "texto": linea[len("<command>"):]}

    m = _RE_MENSAJE.match(linea)
    if m:
        nombre, avatar = separar_nombre(m.group(1))
        return {"tipo": "mensaje", "nombre": nombre or "Anónimo",
                "avatar": avatar, "texto": m.group(2)}

    return {"tipo": "sistema", "texto": linea}
