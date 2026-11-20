"""
Capa de datos: todo lo que el servidor guarda o consulta en SQL Server.

Se usa pymssql (pip3 install pymssql). Una sola conexión compartida por todos
los hilos, protegida con un candado, porque pymssql no es seguro entre hilos.

Cómo se usa el esquema:
  Usuario.estadoUsuario        1 = conectado, 0 = desconectado
  Usuario.fechaConexion        última vez que entró o salió
  TipoChat                     'Global', 'Privado', 'Grupal', 'Canal'
  Relacion_Usuario_Chat        quién pertenece a qué chat (estadoRel 0 = salió)
                               el dueño de un canal es su primera relación (menor idRel)
  Mensaje.estadoMensaje        1 = visible
"""

from __future__ import annotations

import re
import threading

import pymssql

import config

TIPOS_CHAT = ("Global", "Privado", "Grupal", "Canal")
TIPOS_MENSAJE = ("Texto", "GIF", "Imagen")
TABLAS = ("Usuario", "TipoChat", "Chat", "Relacion_Usuario_Chat", "TipoMensaje", "Mensaje")


def _fecha(valor):
    return valor.strftime("%Y-%m-%d %H:%M:%S") if valor else None


class ErrorBD(Exception):
    pass


class BaseDatos:
    def __init__(self, host=config.DB_HOST, port=config.DB_PORT, usuario=config.DB_USER,
                 password=config.DB_PASSWORD, nombre_bd=config.DB_NAME):
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", nombre_bd):
            raise ErrorBD(f"Nombre de base de datos no válido: {nombre_bd!r}")
        self.host, self.port = host, port
        self.db_usuario, self.password = usuario, password
        self.nombre_bd = nombre_bd
        self._lock = threading.RLock()
        self._conn = None
        self.tipo_chat_id = {}      # 'Global' -> idTipoChat
        self.tipo_chat_nombre = {}  # idTipoChat -> 'Global'
        self.tipo_mensaje_id = {}
        self.id_global = None

    # ------------------------------------------------------------------
    # Conexión
    # ------------------------------------------------------------------
    def _abrir(self, base):
        return pymssql.connect(server=self.host, port=str(self.port), user=self.db_usuario,
                               password=self.password, database=base, autocommit=True,
                               login_timeout=10, timeout=30, charset="UTF-8")

    def _sql(self, sql, params=None, traer=None):
        """
        Ejecuta una sentencia.
        traer: None (no devuelve nada), 'uno' (dict o None), 'todos' (lista de dicts).
        Si la conexión se cayó, reconecta una vez y reintenta.
        """
        with self._lock:
            for intento in (1, 2):
                try:
                    if self._conn is None:
                        self._conn = self._abrir(self.nombre_bd)
                    cur = self._conn.cursor(as_dict=True)
                    cur.execute(sql, params)
                    if traer == "uno":
                        return cur.fetchone()
                    if traer == "todos":
                        return cur.fetchall()
                    return None
                except (pymssql.OperationalError, pymssql.InterfaceError):
                    try:
                        if self._conn is not None:
                            self._conn.close()
                    except Exception:
                        pass
                    self._conn = None
                    if intento == 2:
                        raise

    # ------------------------------------------------------------------
    # Preparación al arrancar el servidor
    # ------------------------------------------------------------------
    def preparar(self):
        """Verifica que existan las tablas, completa catálogos y el chat global."""
        # 1) La base y las tablas ya existen: solo se comprueba
        try:
            self._sql("SELECT 1 AS ok", traer="uno")
        except pymssql.Error as e:
            raise ErrorBD(f"No se pudo abrir la base '{self.nombre_bd}' en {self.host}:{self.port}. "
                          f"Revisa DB_NAME, usuario y contraseña en config.py.\n{e}") from e
        faltan = [t for t in TABLAS
                  if self._sql("SELECT OBJECT_ID(%s, 'U') AS id", (f"dbo.{t}",), traer="uno")["id"] is None]
        if faltan:
            raise ErrorBD(f"En la base '{self.nombre_bd}' faltan las tablas: {', '.join(faltan)}. "
                          "Ejecuta sql/esquema.sql o revisa DB_NAME en config.py.")

        # 2) Catálogos (solo agrega los que falten)
        for tipo in TIPOS_CHAT:
            self._sql("IF NOT EXISTS (SELECT 1 FROM TipoChat WHERE tipoChat = %(t)s) "
                      "INSERT INTO TipoChat (tipoChat) VALUES (%(t)s)", {"t": tipo})
        for tipo in TIPOS_MENSAJE:
            self._sql("IF NOT EXISTS (SELECT 1 FROM TipoMensaje WHERE tipoMensaje = %(t)s) "
                      "INSERT INTO TipoMensaje (tipoMensaje) VALUES (%(t)s)", {"t": tipo})
        for fila in self._sql("SELECT idTipoChat, tipoChat FROM TipoChat", traer="todos"):
            self.tipo_chat_id[fila["tipoChat"]] = fila["idTipoChat"]
            self.tipo_chat_nombre[fila["idTipoChat"]] = fila["tipoChat"]
        for fila in self._sql("SELECT idTipoMensaje, tipoMensaje FROM TipoMensaje", traer="todos"):
            self.tipo_mensaje_id[fila["tipoMensaje"]] = fila["idTipoMensaje"]

        # 3) El chat global (uno solo)
        fila = self._sql("SELECT TOP 1 idChat FROM Chat WHERE idTipoChat = %s AND estadoChat = 1 "
                         "ORDER BY idChat", (self.tipo_chat_id["Global"],), traer="uno")
        if fila:
            self.id_global = fila["idChat"]
        else:
            self.id_global = self._sql(
                "INSERT INTO Chat (nombreChat, idTipoChat) OUTPUT INSERTED.idChat VALUES (%s, %s)",
                (config.NOMBRE_CHAT_GLOBAL, self.tipo_chat_id["Global"]), traer="uno")["idChat"]

        # 4) Si el servidor se cerró de golpe, nadie sigue conectado
        self._sql("UPDATE Usuario SET estadoUsuario = 0 WHERE estadoUsuario = 1")

    def ahora(self) -> str:
        """Hora actual de SQL Server (el cliente la usa para ajustar su zona horaria)."""
        return _fecha(self._sql("SELECT GETDATE() AS ahora", traer="uno")["ahora"])

    # ------------------------------------------------------------------
    # Usuarios
    # ------------------------------------------------------------------
    def login(self, nombre: str, imagen: int) -> dict:
        """Crea el usuario o actualiza su avatar; lo marca conectado y lo une al global."""
        for _ in range(2):
            fila = self._sql("SELECT idUsuario FROM Usuario WHERE nombreCompleto = %s",
                             (nombre,), traer="uno")
            if fila:
                self._sql("UPDATE Usuario SET idImagen = %s, fechaConexion = GETDATE(), "
                          "estadoUsuario = 1 WHERE idUsuario = %s", (imagen, fila["idUsuario"]))
                id_usuario = fila["idUsuario"]
                break
            try:
                id_usuario = self._sql(
                    "INSERT INTO Usuario (idImagen, nombreCompleto, estadoUsuario) "
                    "OUTPUT INSERTED.idUsuario VALUES (%s, %s, 1)",
                    (imagen, nombre), traer="uno")["idUsuario"]
                break
            except pymssql.IntegrityError:
                continue  # otro cliente lo creó al mismo tiempo: se vuelve a buscar
        else:
            raise ErrorBD(f"No se pudo registrar al usuario {nombre!r}")
        self.unir(id_usuario, self.id_global)
        return self.usuario(id_usuario)

    def usuario(self, id_usuario: int):
        fila = self._sql("SELECT idUsuario, nombreCompleto, idImagen FROM Usuario "
                         "WHERE idUsuario = %s", (id_usuario,), traer="uno")
        if not fila:
            return None
        return {"id": fila["idUsuario"], "nombre": fila["nombreCompleto"], "imagen": fila["idImagen"]}

    def desconectar(self, id_usuario: int):
        self._sql("UPDATE Usuario SET estadoUsuario = 0, fechaConexion = GETDATE() "
                  "WHERE idUsuario = %s", (id_usuario,))

    # ------------------------------------------------------------------
    # Pertenencia a chats
    # ------------------------------------------------------------------
    def unir(self, id_usuario: int, id_chat: int):
        self._sql("""
            IF EXISTS (SELECT 1 FROM Relacion_Usuario_Chat WHERE idUsuario = %(u)s AND idChat = %(c)s)
                UPDATE Relacion_Usuario_Chat SET estadoRel = 1
                WHERE idUsuario = %(u)s AND idChat = %(c)s
            ELSE
                INSERT INTO Relacion_Usuario_Chat (idUsuario, idChat) VALUES (%(u)s, %(c)s)
        """, {"u": id_usuario, "c": id_chat})

    def salir(self, id_usuario: int, id_chat: int):
        self._sql("UPDATE Relacion_Usuario_Chat SET estadoRel = 0 "
                  "WHERE idUsuario = %s AND idChat = %s", (id_usuario, id_chat))

    def es_miembro(self, id_usuario: int, id_chat: int) -> bool:
        fila = self._sql("""
            SELECT 1 AS si FROM Relacion_Usuario_Chat r
            JOIN Chat c ON c.idChat = r.idChat
            WHERE r.idUsuario = %s AND r.idChat = %s AND r.estadoRel = 1 AND c.estadoChat = 1
        """, (id_usuario, id_chat), traer="uno")
        return fila is not None

    def miembros(self, id_chat: int) -> list:
        filas = self._sql("SELECT idUsuario FROM Relacion_Usuario_Chat "
                          "WHERE idChat = %s AND estadoRel = 1", (id_chat,), traer="todos")
        return [f["idUsuario"] for f in filas]

    def info_chat(self, id_chat: int):
        """{'tipo': 'Canal', 'dueno': idUsuario} de un chat activo, o None."""
        fila = self._sql("""
            SELECT c.idTipoChat,
                   (SELECT TOP 1 r.idUsuario FROM Relacion_Usuario_Chat r
                    WHERE r.idChat = c.idChat ORDER BY r.idRel) AS dueno
            FROM Chat c WHERE c.idChat = %s AND c.estadoChat = 1
        """, (id_chat,), traer="uno")
        if not fila:
            return None
        return {"tipo": self.tipo_chat_nombre.get(fila["idTipoChat"]), "dueno": fila["dueno"]}

    # ------------------------------------------------------------------
    # Chats
    # ------------------------------------------------------------------
    def chats_de(self, id_usuario: int, id_chat: int = None) -> list:
        """
        Resumen de los chats de un usuario (o de uno solo si se pasa id_chat),
        con el último mensaje, el número de miembros y, en los privados, el otro usuario.
        """
        filtro = "AND c.idChat = %(c)s" if id_chat is not None else ""
        filas = self._sql(f"""
            SELECT c.idChat, c.nombreChat, c.idTipoChat, c.fechaCreacion,
                   otro.idUsuario AS idOtro, otro.nombreCompleto AS nombreOtro,
                   otro.idImagen AS imagenOtro, otro.fechaConexion AS vistoOtro,
                   duen.idUsuario AS idDueno,
                   (SELECT COUNT(*) FROM Relacion_Usuario_Chat r4
                    WHERE r4.idChat = c.idChat AND r4.estadoRel = 1) AS miembros,
                   ult.mensajeTexto AS ultTexto, ult.fechaMensaje AS ultFecha,
                   ult.idUsuario AS ultIdUsuario, ult.nombreCompleto AS ultAutor
            FROM Chat c
            JOIN Relacion_Usuario_Chat r
                 ON r.idChat = c.idChat AND r.idUsuario = %(u)s AND r.estadoRel = 1
            OUTER APPLY (SELECT TOP 1 u2.idUsuario, u2.nombreCompleto, u2.idImagen, u2.fechaConexion
                         FROM Relacion_Usuario_Chat r2
                         JOIN Usuario u2 ON u2.idUsuario = r2.idUsuario
                         WHERE r2.idChat = c.idChat AND r2.idUsuario <> %(u)s
                         ORDER BY r2.idRel) otro
            OUTER APPLY (SELECT TOP 1 r3.idUsuario FROM Relacion_Usuario_Chat r3
                         WHERE r3.idChat = c.idChat ORDER BY r3.idRel) duen
            OUTER APPLY (SELECT TOP 1 m.mensajeTexto, m.fechaMensaje, m.idUsuario, u5.nombreCompleto
                         FROM Mensaje m JOIN Usuario u5 ON u5.idUsuario = m.idUsuario
                         WHERE m.idChat = c.idChat AND m.estadoMensaje = 1
                         ORDER BY m.idMensaje DESC) ult
            WHERE c.estadoChat = 1 {filtro}
        """, {"u": id_usuario, "c": id_chat}, traer="todos")

        chats = []
        for f in filas:
            tipo = self.tipo_chat_nombre.get(f["idTipoChat"], "Grupal")
            privado = tipo == "Privado"
            ultimo = None
            if f["ultFecha"] is not None:
                texto = f["ultTexto"] or ""
                ultimo = {"texto": texto[:120], "autor": f["ultAutor"],
                          "idUsuario": f["ultIdUsuario"], "fecha": _fecha(f["ultFecha"])}
            chats.append({
                "id": f["idChat"],
                "tipo": tipo,
                "nombre": (f["nombreOtro"] or "Usuario") if privado else (f["nombreChat"] or tipo),
                "imagen": f["imagenOtro"] if privado else None,
                "idOtro": f["idOtro"] if privado else None,
                "vistoOtro": _fecha(f["vistoOtro"]) if privado else None,
                "idDueno": f["idDueno"],
                "miembros": f["miembros"],
                "creado": _fecha(f["fechaCreacion"]),
                "ultimo": ultimo,
            })
        return chats

    def crear_chat(self, nombre, tipo: str, integrantes: list) -> int:
        """Crea el chat y une a los integrantes en orden (el primero queda como dueño)."""
        id_chat = self._sql(
            "INSERT INTO Chat (nombreChat, idTipoChat) OUTPUT INSERTED.idChat VALUES (%s, %s)",
            (nombre, self.tipo_chat_id[tipo]), traer="uno")["idChat"]
        for id_usuario in integrantes:
            self.unir(id_usuario, id_chat)
        return id_chat

    def buscar_o_crear_privado(self, yo: int, otro: int):
        """Devuelve (idChat, creado). Si ya existía, reactiva a ambos."""
        fila = self._sql("""
            SELECT TOP 1 c.idChat FROM Chat c
            JOIN Relacion_Usuario_Chat a ON a.idChat = c.idChat AND a.idUsuario = %(a)s
            JOIN Relacion_Usuario_Chat b ON b.idChat = c.idChat AND b.idUsuario = %(b)s
            WHERE c.idTipoChat = %(t)s AND c.estadoChat = 1
            ORDER BY c.idChat
        """, {"a": yo, "b": otro, "t": self.tipo_chat_id["Privado"]}, traer="uno")
        if fila:
            self.unir(yo, fila["idChat"])
            self.unir(otro, fila["idChat"])
            return fila["idChat"], False
        return self.crear_chat(None, "Privado", [yo, otro]), True

    def eliminar_chat(self, id_chat: int):
        self._sql("UPDATE Chat SET estadoChat = 0 WHERE idChat = %s", (id_chat,))

    def canales(self, id_usuario: int) -> list:
        filas = self._sql("""
            SELECT c.idChat, c.nombreChat, c.fechaCreacion,
                   (SELECT COUNT(*) FROM Relacion_Usuario_Chat r
                    WHERE r.idChat = c.idChat AND r.estadoRel = 1) AS seguidores,
                   (SELECT TOP 1 u.nombreCompleto FROM Relacion_Usuario_Chat r
                    JOIN Usuario u ON u.idUsuario = r.idUsuario
                    WHERE r.idChat = c.idChat ORDER BY r.idRel) AS dueno,
                   (SELECT TOP 1 r.idUsuario FROM Relacion_Usuario_Chat r
                    WHERE r.idChat = c.idChat ORDER BY r.idRel) AS idDueno,
                   CASE WHEN EXISTS (SELECT 1 FROM Relacion_Usuario_Chat r
                                     WHERE r.idChat = c.idChat AND r.idUsuario = %(u)s
                                       AND r.estadoRel = 1)
                        THEN 1 ELSE 0 END AS siguiendo
            FROM Chat c
            WHERE c.idTipoChat = %(t)s AND c.estadoChat = 1
            ORDER BY seguidores DESC, c.idChat DESC
        """, {"u": id_usuario, "t": self.tipo_chat_id["Canal"]}, traer="todos")
        return [{"id": f["idChat"], "nombre": f["nombreChat"] or "Canal",
                 "seguidores": f["seguidores"], "dueno": f["dueno"], "idDueno": f["idDueno"],
                 "siguiendo": bool(f["siguiendo"]), "creado": _fecha(f["fechaCreacion"])}
                for f in filas]

    # ------------------------------------------------------------------
    # Mensajes
    # ------------------------------------------------------------------
    def historial(self, id_chat: int, limite: int = config.HISTORIAL) -> list:
        filas = self._sql("""
            SELECT TOP (%(n)s) m.idMensaje, m.idUsuario, u.nombreCompleto, u.idImagen,
                   m.mensajeTexto, m.fechaMensaje, tm.tipoMensaje
            FROM Mensaje m
            JOIN Usuario u ON u.idUsuario = m.idUsuario
            JOIN TipoMensaje tm ON tm.idTipoMensaje = m.idTipoMensaje
            WHERE m.idChat = %(c)s AND m.estadoMensaje = 1
            ORDER BY m.idMensaje DESC
        """, {"n": int(limite), "c": id_chat}, traer="todos")
        return [{"id": f["idMensaje"], "idUsuario": f["idUsuario"], "nombre": f["nombreCompleto"],
                 "imagen": f["idImagen"], "texto": f["mensajeTexto"], "tipo": f["tipoMensaje"],
                 "fecha": _fecha(f["fechaMensaje"])}
                for f in reversed(filas)]

    def guardar_mensaje(self, id_chat: int, usuario: dict, texto: str, tipo: str = "Texto") -> dict:
        fila = self._sql("""
            INSERT INTO Mensaje (idChat, idUsuario, idTipoMensaje, mensajeTexto)
            OUTPUT INSERTED.idMensaje, INSERTED.fechaMensaje
            VALUES (%s, %s, %s, %s)
        """, (id_chat, usuario["id"], self.tipo_mensaje_id[tipo], texto), traer="uno")
        return {"id": fila["idMensaje"], "idUsuario": usuario["id"], "nombre": usuario["nombre"],
                "imagen": usuario["imagen"], "texto": texto, "tipo": tipo,
                "fecha": _fecha(fila["fechaMensaje"])}
