"""
Protocolo compartido entre server.py y cliente.py.

Cada mensaje es un objeto JSON en UNA línea, terminado en "\\n" (JSON Lines).
TCP es un flujo de bytes: un recv() puede traer medio mensaje o varios juntos,
así que LectorLineas acumula bytes y solo entrega líneas completas.

Cliente -> servidor (campo "accion"):
    login            {nombre, imagen}
    abrir_chat       {idChat}
    enviar           {idChat, texto}
    crear_privado    {idUsuario}
    crear_grupo      {nombre, miembros: [idUsuario, ...]}
    crear_canal      {nombre}
    explorar_canales {}
    seguir_canal     {idChat}
    salir_chat       {idChat}
    eliminar_canal   {idChat}

Servidor -> cliente (campo "tipo"):
    bienvenida       {usuario, chats, usuarios, idGlobal, horaServidor}
    error_login      {mensaje}
    usuarios         {lista}             usuarios conectados
    chat             {chat, abrir}       chat nuevo o actualizado
    chat_eliminado   {idChat}
    historial        {idChat, mensajes}
    mensaje          {idChat, mensaje}
    canales          {lista}             resultado de explorar_canales
    error            {mensaje}
"""

import json

MAX_LINEA = 2_000_000  # bytes; protege contra clientes que nunca mandan "\n"


def codificar(obj) -> bytes:
    """dict -> bytes listos para sendall()."""
    return (json.dumps(obj, ensure_ascii=False, default=str) + "\n").encode("utf-8")


class LineaDemasiadoLarga(Exception):
    pass


class LectorLineas:
    """Junta los bytes recibidos y devuelve los mensajes JSON completos."""

    def __init__(self):
        self._buffer = b""

    def alimentar(self, datos: bytes) -> list:
        self._buffer += datos
        mensajes = []
        while b"\n" in self._buffer:
            linea, self._buffer = self._buffer.split(b"\n", 1)
            if not linea.strip():
                continue
            try:
                obj = json.loads(linea.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                continue  # línea corrupta: se ignora
            if isinstance(obj, dict):
                mensajes.append(obj)
        if len(self._buffer) > MAX_LINEA:
            raise LineaDemasiadoLarga()
        return mensajes
