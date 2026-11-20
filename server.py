"""
Servidor del chat distribuido.

- Un hilo por cliente (threading).
- Mensajes en JSON por líneas (ver protocolo.py).
- Todo se guarda en SQL Server (ver db.py).

Uso:
    python3 server.py              # puerto de config.py (3011)
    python3 server.py 3012         # otro puerto
"""

from __future__ import annotations

import socket
import sys
import threading
from datetime import datetime

import config
import protocolo


def log(*partes):
    print(datetime.now().strftime("[%H:%M:%S]"), *partes, flush=True)


class ErrorCliente(Exception):
    """Error que se le muestra al usuario (petición inválida o sin permiso)."""


class Sesion:
    """Una conexión de cliente. El candado evita que dos hilos escriban a la vez en el socket."""

    def __init__(self, conn, addr):
        self.conn = conn
        self.addr = addr
        self.usuario = None  # {"id", "nombre", "imagen"} después del login
        self._lock = threading.Lock()

    def enviar(self, obj) -> bool:
        datos = protocolo.codificar(obj)
        with self._lock:
            try:
                self.conn.sendall(datos)
                return True
            except OSError:
                return False

    def cerrar(self):
        try:
            self.conn.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.conn.close()


class Servidor:
    def __init__(self, bd, host=config.HOST, port=config.PORT):
        self.bd = bd
        self.host, self.port = host, port
        self.sesiones = {}             # idUsuario -> Sesion (usuarios conectados)
        self._lock = threading.Lock()
        self.socket = None
        self.acciones = {
            "abrir_chat": self.abrir_chat,
            "enviar": self.enviar,
            "crear_privado": self.crear_privado,
            "crear_grupo": self.crear_grupo,
            "crear_canal": self.crear_canal,
            "explorar_canales": self.explorar_canales,
            "seguir_canal": self.seguir_canal,
            "salir_chat": self.salir_chat,
            "eliminar_canal": self.eliminar_canal,
        }

    # ------------------------------------------------------------------
    # Arranque y conexiones
    # ------------------------------------------------------------------
    def iniciar(self):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind((self.host, self.port))
        self.socket.listen(100)
        log(f"Escuchando conexiones en {self.host}:{self.port}")
        while True:
            conn, addr = self.socket.accept()
            log("Conexión nueva:", addr)
            threading.Thread(target=self.atender, args=(Sesion(conn, addr),), daemon=True).start()

    def atender(self, sesion: Sesion):
        lector = protocolo.LectorLineas()
        try:
            while True:
                datos = sesion.conn.recv(4096)
                if not datos:
                    break
                for peticion in lector.alimentar(datos):
                    if sesion.usuario is None:
                        if not self.login(sesion, peticion):
                            return
                    else:
                        self.despachar(sesion, peticion)
        except (OSError, protocolo.LineaDemasiadoLarga):
            pass
        finally:
            self.desconectar(sesion)

    def despachar(self, sesion: Sesion, peticion: dict):
        accion = peticion.get("accion")
        funcion = self.acciones.get(accion)
        try:
            if funcion is None:
                raise ErrorCliente(f"Acción desconocida: {accion}")
            funcion(sesion, peticion)
        except ErrorCliente as e:
            sesion.enviar({"tipo": "error", "mensaje": str(e)})
        except (KeyError, TypeError, ValueError):
            sesion.enviar({"tipo": "error", "mensaje": "Petición mal formada."})
        except Exception as e:  # error de base de datos u otro inesperado
            log(f"ERROR en '{accion}' de {sesion.usuario['nombre']}: {e!r}")
            sesion.enviar({"tipo": "error", "mensaje": "Error del servidor, intenta de nuevo."})

    # ------------------------------------------------------------------
    # Login / logout
    # ------------------------------------------------------------------
    def login(self, sesion: Sesion, peticion: dict) -> bool:
        def rechazar(texto):
            sesion.enviar({"tipo": "error_login", "mensaje": texto})
            sesion.cerrar()
            return False

        if peticion.get("accion") != "login":
            return rechazar("Primero debes iniciar sesión.")
        nombre = " ".join(str(peticion.get("nombre", "")).split())  # quita espacios dobles
        try:
            imagen = int(peticion.get("imagen", 1))
        except (TypeError, ValueError):
            imagen = 1
        imagen = min(max(imagen, 1), config.NUM_IMAGENES)
        if not nombre:
            return rechazar("Escribe tu nombre.")
        if len(nombre) > config.MAX_NOMBRE:
            return rechazar(f"El nombre puede tener máximo {config.MAX_NOMBRE} caracteres.")

        try:
            usuario = self.bd.login(nombre, imagen)
        except Exception as e:
            log("ERROR en login:", repr(e))
            return rechazar("No se pudo guardar el usuario en la base de datos.")

        with self._lock:
            if usuario["id"] in self.sesiones:
                ocupado = True
            else:
                ocupado = False
                self.sesiones[usuario["id"]] = sesion
                sesion.usuario = usuario
        if ocupado:
            return rechazar(f"'{usuario['nombre']}' ya está conectado. Usa otro nombre.")

        log(f"Login: {usuario['nombre']} (id {usuario['id']}, avatar {usuario['imagen']})")
        sesion.enviar({
            "tipo": "bienvenida",
            "usuario": usuario,
            "chats": self.bd.chats_de(usuario["id"]),
            "usuarios": self.lista_activos(),
            "idGlobal": self.bd.id_global,
            "horaServidor": self.bd.ahora(),
        })
        self.avisar_usuarios()
        return True

    def desconectar(self, sesion: Sesion):
        sesion.cerrar()
        usuario = sesion.usuario
        if usuario is None:
            return
        with self._lock:
            if self.sesiones.get(usuario["id"]) is sesion:
                del self.sesiones[usuario["id"]]
            else:
                return
        try:
            self.bd.desconectar(usuario["id"])
        except Exception as e:
            log("ERROR al marcar desconexión:", repr(e))
        log(f"Salió: {usuario['nombre']}")
        self.avisar_usuarios()

    # ------------------------------------------------------------------
    # Envío a varios clientes
    # ------------------------------------------------------------------
    def lista_activos(self) -> list:
        with self._lock:
            return sorted((s.usuario for s in self.sesiones.values()), key=lambda u: u["nombre"].lower())

    def enviar_a(self, ids, obj):
        with self._lock:
            destinos = [self.sesiones[i] for i in set(ids) if i in self.sesiones]
        for sesion in destinos:
            sesion.enviar(obj)

    def avisar_usuarios(self):
        lista = self.lista_activos()
        self.enviar_a([u["id"] for u in lista], {"tipo": "usuarios", "lista": lista})

    def notificar_chat(self, id_chat: int, ids, abrir_para: int = None):
        """Manda a cada usuario conectado su versión del resumen del chat (nuevo o actualizado)."""
        with self._lock:
            conectados = [i for i in set(ids) if i in self.sesiones]
        for id_usuario in conectados:
            resumen = self.bd.chats_de(id_usuario, id_chat)
            if resumen:
                self.enviar_a([id_usuario], {"tipo": "chat", "chat": resumen[0],
                                             "abrir": id_usuario == abrir_para})

    # ------------------------------------------------------------------
    # Validaciones
    # ------------------------------------------------------------------
    @staticmethod
    def _entero(peticion, campo) -> int:
        try:
            return int(peticion[campo])
        except (KeyError, TypeError, ValueError):
            raise ErrorCliente(f"Falta o es inválido: {campo}") from None

    @staticmethod
    def _nombre_chat(peticion) -> str:
        nombre = " ".join(str(peticion.get("nombre", "")).split())
        if not nombre:
            raise ErrorCliente("Escribe un nombre.")
        if len(nombre) > config.MAX_NOMBRE_CHAT:
            raise ErrorCliente(f"El nombre puede tener máximo {config.MAX_NOMBRE_CHAT} caracteres.")
        return nombre

    def _chat_de_miembro(self, yo: int, id_chat: int) -> dict:
        info = self.bd.info_chat(id_chat)
        if info is None or not self.bd.es_miembro(yo, id_chat):
            raise ErrorCliente("No perteneces a ese chat.")
        return info

    # ------------------------------------------------------------------
    # Acciones
    # ------------------------------------------------------------------
    def abrir_chat(self, sesion, peticion):
        id_chat = self._entero(peticion, "idChat")
        self._chat_de_miembro(sesion.usuario["id"], id_chat)
        sesion.enviar({"tipo": "historial", "idChat": id_chat, "mensajes": self.bd.historial(id_chat)})

    def enviar(self, sesion, peticion):
        yo = sesion.usuario
        id_chat = self._entero(peticion, "idChat")
        texto = str(peticion.get("texto", "")).strip()
        if not texto:
            return
        if len(texto) > config.MAX_MENSAJE:
            raise ErrorCliente(f"El mensaje puede tener máximo {config.MAX_MENSAJE} caracteres.")
        info = self._chat_de_miembro(yo["id"], id_chat)
        if info["tipo"] == "Canal" and info["dueno"] != yo["id"]:
            raise ErrorCliente("Solo el administrador del canal puede publicar.")

        mensaje = self.bd.guardar_mensaje(id_chat, yo, texto)
        self.enviar_a(self.bd.miembros(id_chat), {"tipo": "mensaje", "idChat": id_chat, "mensaje": mensaje})

    def crear_privado(self, sesion, peticion):
        yo = sesion.usuario["id"]
        otro = self._entero(peticion, "idUsuario")
        if otro == yo:
            raise ErrorCliente("No puedes abrir un chat contigo mismo.")
        if self.bd.usuario(otro) is None:
            raise ErrorCliente("Ese usuario no existe.")
        id_chat, creado = self.bd.buscar_o_crear_privado(yo, otro)
        self.notificar_chat(id_chat, [yo, otro] if creado else [yo], abrir_para=yo)

    def crear_grupo(self, sesion, peticion):
        yo = sesion.usuario["id"]
        nombre = self._nombre_chat(peticion)
        try:
            miembros = []
            for valor in peticion.get("miembros", []):
                id_usuario = int(valor)
                if id_usuario != yo and id_usuario not in miembros:
                    miembros.append(id_usuario)
        except (TypeError, ValueError):
            raise ErrorCliente("Lista de miembros inválida.") from None
        if not miembros:
            raise ErrorCliente("Elige al menos a una persona para el grupo.")
        for id_usuario in miembros:
            if self.bd.usuario(id_usuario) is None:
                raise ErrorCliente("Uno de los usuarios no existe.")
        id_chat = self.bd.crear_chat(nombre, "Grupal", [yo] + miembros)
        log(f"Grupo '{nombre}' creado por {sesion.usuario['nombre']}")
        self.notificar_chat(id_chat, [yo] + miembros, abrir_para=yo)

    def crear_canal(self, sesion, peticion):
        yo = sesion.usuario["id"]
        nombre = self._nombre_chat(peticion)
        id_chat = self.bd.crear_chat(nombre, "Canal", [yo])
        log(f"Canal '{nombre}' creado por {sesion.usuario['nombre']}")
        self.notificar_chat(id_chat, [yo], abrir_para=yo)

    def explorar_canales(self, sesion, peticion):
        sesion.enviar({"tipo": "canales", "lista": self.bd.canales(sesion.usuario["id"])})

    def seguir_canal(self, sesion, peticion):
        yo = sesion.usuario["id"]
        id_chat = self._entero(peticion, "idChat")
        info = self.bd.info_chat(id_chat)
        if info is None or info["tipo"] != "Canal":
            raise ErrorCliente("Ese canal no existe.")
        self.bd.unir(yo, id_chat)
        # Todos ven el nuevo número de seguidores; solo el que lo siguió lo abre
        self.notificar_chat(id_chat, self.bd.miembros(id_chat), abrir_para=yo)

    def salir_chat(self, sesion, peticion):
        yo = sesion.usuario["id"]
        id_chat = self._entero(peticion, "idChat")
        info = self._chat_de_miembro(yo, id_chat)
        if info["tipo"] not in ("Grupal", "Canal"):
            raise ErrorCliente("De este chat no se puede salir.")
        if info["tipo"] == "Canal" and info["dueno"] == yo:
            raise ErrorCliente("Eres el administrador: elimina el canal en lugar de salir.")
        self.bd.salir(yo, id_chat)
        sesion.enviar({"tipo": "chat_eliminado", "idChat": id_chat})
        self.notificar_chat(id_chat, self.bd.miembros(id_chat))

    def eliminar_canal(self, sesion, peticion):
        yo = sesion.usuario["id"]
        id_chat = self._entero(peticion, "idChat")
        info = self._chat_de_miembro(yo, id_chat)
        if info["tipo"] != "Canal" or info["dueno"] != yo:
            raise ErrorCliente("Solo el administrador puede eliminar el canal.")
        seguidores = self.bd.miembros(id_chat)
        self.bd.eliminar_chat(id_chat)
        log(f"Canal {id_chat} eliminado por {sesion.usuario['nombre']}")
        self.enviar_a(seguidores, {"tipo": "chat_eliminado", "idChat": id_chat})


def main():
    from db import BaseDatos, ErrorBD  # aquí, para que las pruebas no necesiten pymssql

    port = int(sys.argv[1]) if len(sys.argv) > 1 else config.PORT
    log(f"Conectando a SQL Server {config.DB_HOST}:{config.DB_PORT}, base '{config.DB_NAME}'...")
    bd = BaseDatos()
    try:
        bd.preparar()
    except ErrorBD as e:
        log(f"ERROR: {e}")
        sys.exit(1)
    except Exception as e:
        log(f"ERROR al conectar con la base de datos: {e!r}")
        log("Revisa que el puerto 1433 sea accesible y los datos de config.py.")
        sys.exit(1)
    log(f"Base de datos lista (chat global id {bd.id_global}).")

    servidor = Servidor(bd, port=port)
    try:
        servidor.iniciar()
    except KeyboardInterrupt:
        log("Servidor detenido.")
    except OSError as e:
        log(f"ERROR: no se pudo usar el puerto {port}: {e}")
    finally:
        if servidor.socket:
            servidor.socket.close()


if __name__ == "__main__":
    main()
