from __future__ import annotations
import queue
import random
import socket
import sys
import threading
import tkinter as tk
from datetime import date, datetime, timedelta
from pathlib import Path
from tkinter import messagebox
import protocolo
import ui
from ui import (BLANCO, CAMPO, FONDO_CHAT, GRIS, GRIS_CLARO, LINEA, ROJO, TEXTO, VERDE,
                VERDE_HOVER, VERDE_OSCURO, VERDE_SUAVE, Boton, Entrada, ListaScroll, fuente,
                recortar)

try:
    from imagenes import Avatares
except ImportError:
    print("Falta Pillow. Instálalo con:  pip3 install pillow")
    sys.exit(1)

# ---------------- Configuración ----------------
SERVIDOR_POR_DEFECTO = "18.190.171.148:3011"
PUERTO_POR_DEFECTO = 3011
CARPETA_AVATARES = Path(__file__).resolve().parent / "avatares"
NUM_AVATARES = 20
MAX_NOMBRE = 50
MAX_MENSAJE = 4000
TEXTO_SOBRE_VERDE = "#334250"   # texto secundario legible sobre #B5FFA8
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]

# Conexión con el servidor en un hilo aparte
class Red:

    def __init__(self, cola: queue.Queue):
        self.cola = cola
        self.sock = None
        self._lock = threading.Lock()

    def conectar(self, host, port, login: dict):
        self.cerrar()
        threading.Thread(target=self._trabajar, args=(host, port, login), daemon=True).start()

    def _trabajar(self, host, port, login):
        try:
            sock = socket.create_connection((host, port), timeout=6)
            sock.settimeout(None)
        except socket.timeout:
            self.cola.put(("error_conexion", f"No hubo respuesta de {host}:{port} (tiempo agotado). "
                                             "¿El puerto está abierto?"))
            return
        except ConnectionRefusedError:
            self.cola.put(("error_conexion", f"{host}:{port} rechazó la conexión. "
                                             "¿Está corriendo server.py?"))
            return
        except OSError as e:
            self.cola.put(("error_conexion", f"No se pudo conectar a {host}:{port}: {e}"))
            return
        self.sock = sock
        self.enviar(login)
        lector = protocolo.LectorLineas()
        try:
            while True:
                datos = sock.recv(65536)
                if not datos:
                    break
                for mensaje in lector.alimentar(datos):
                    self.cola.put(("msg", mensaje))
        except (OSError, protocolo.LineaDemasiadoLarga):
            pass
        if self.sock is sock:  # si no fue un cierre a propósito
            self.sock = None
            self.cola.put(("desconectado", None))

    def enviar(self, obj) -> bool:
        sock = self.sock
        if sock is None:
            return False
        with self._lock:
            try:
                sock.sendall(protocolo.codificar(obj))
                return True
            except OSError:
                return False

    @property
    def conectada(self) -> bool:
        return self.sock is not None

    def cerrar(self):
        sock, self.sock = self.sock, None
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()

# Vista
class App(tk.Tk):
    def __init__(self, servidor_inicial: str):
        super().__init__()
        self.title("Wasap")
        self.configure(bg=BLANCO)
        try:
            self.avatares = Avatares(CARPETA_AVATARES, NUM_AVATARES)
        except Exception as e:
            self.withdraw()
            messagebox.showerror("No hay imagenes de avatares")
            self.destroy()
            sys.exit(1)

        self.cola = queue.Queue()
        self.red = Red(self.cola)
        self.servidor_inicial = servidor_inicial
        self.vista = None
        self.seleccion = random.randint(1, self.avatares.total)
        self.datos_login = None          # (host, port, nombre, imagen) para reconectar
        self.desfase = timedelta(0)      # hora local - hora del servidor

        # Estado del chat
        self.yo = None
        self.id_global = None
        self.chats = {}       # idChat -> resumen
        self.mensajes = {}    # idChat -> lista (None = cargando)
        self.pendientes = {}  # mensajes que llegaron mientras se cargaba el historial
        self.no_leidos = {}
        self.activos = {}     # idUsuario -> usuario conectado
        self.visto = {}       # idUsuario -> fecha (hora del servidor) en que se desconectó
        self.actual = None
        self.pestana = "chats"
        self.ancho_burbuja = 420
        self.dlg_canales = None
        self._repintar_lista_pendiente = False

        ui.instalar_rueda(self)
        self.protocol("WM_DELETE_WINDOW", self.cerrar)
        self.mostrar_login()
        self.after(40, self._procesar_cola)

    # Utilidades
    def _limpiar_ventana(self):
        for hijo in self.winfo_children():
            if not isinstance(hijo, tk.Menu):
                hijo.destroy()

    def _fecha(self, texto):
        """Fecha del servidor -> datetime en la hora local de esta computadora."""
        try:
            return datetime.strptime(texto, "%Y-%m-%d %H:%M:%S") + self.desfase
        except (TypeError, ValueError):
            return None

    def _hora_corta(self, texto) -> str:
        f = self._fecha(texto)
        if f is None:
            return ""
        if f.date() == date.today():
            return f.strftime("%H:%M")
        if f.date() == date.today() - timedelta(days=1):
            return "Ayer"
        return f.strftime("%d/%m/%y")

    def _dia_bonito(self, f: datetime) -> str:
        if f.date() == date.today():
            return "Hoy"
        if f.date() == date.today() - timedelta(days=1):
            return "Ayer"
        return f"{f.day} de {MESES[f.month - 1]} de {f.year}"

    def _ultima_vez(self, texto) -> str:
        f = self._fecha(texto)
        if f is None:
            return "desconectado"
        if f.date() == date.today():
            return f"últ. vez hoy a las {f.strftime('%H:%M')}"
        if f.date() == date.today() - timedelta(days=1):
            return f"últ. vez ayer a las {f.strftime('%H:%M')}"
        return f"últ. vez el {f.strftime('%d/%m/%y')}"

    def _imagen_chat(self, chat, tam):
        if chat["tipo"] == "Privado":
            return self.avatares.avatar(chat["imagen"], tam)
        return self.avatares.icono(chat["tipo"], tam)

    def aviso(self, texto):
        """Mensaje flotante temporal (errores del servidor, etc.)."""
        if getattr(self, "_toast", None) is not None and self._toast.winfo_exists():
            self._toast.destroy()
        self._toast = tk.Label(self, text=texto, bg=TEXTO, fg=BLANCO, font=fuente(12),
                               padx=16, pady=9, wraplength=420)
        self._toast.place(relx=0.5, rely=1.0, y=-96, anchor="s")
        toast = self._toast
        self.after(3800, lambda: toast.winfo_exists() and toast.destroy())

    def cerrar(self):
        self.red.cerrar()
        self.destroy()

    # Cola de eventos (único lugar donde se toca la interfaz con datos de red)
    def _procesar_cola(self):
        try:
            while True:
                tipo, dato = self.cola.get_nowait()
                if tipo == "msg":
                    funcion = getattr(self, "ev_" + str(dato.get("tipo")), None)
                    if funcion:
                        try:
                            funcion(dato)
                        except Exception as e:  # un evento raro no debe tumbar la app
                            print("Error procesando", dato.get("tipo"), repr(e))
                elif tipo == "error_conexion":
                    self.ev_error_conexion(dato)
                elif tipo == "desconectado":
                    self.ev_desconectado()
        except queue.Empty:
            pass
        if self._repintar_lista_pendiente:
            self._repintar_lista_pendiente = False
            self._render_lista()
        self.after(40, self._procesar_cola)

    def _pedir_lista(self):
        """Agrupa varios repintados de la lista en uno solo."""
        self._repintar_lista_pendiente = True


    # Login
    def mostrar_login(self):
        self._limpiar_ventana()
        self.vista = "login"
        self.resizable(False, False)
        self.minsize(1, 1)
        ui.centrar(self, 460, 550)

        raiz = tk.Frame(self, bg=BLANCO)
        raiz.pack(fill="both", expand=True)

        banda = tk.Frame(raiz, bg=VERDE, height=60)
        banda.pack(fill="x")
        banda.pack_propagate(False)
        tk.Label(banda, text="Wasap", font=fuente(30, "bold"), bg=VERDE, fg=TEXTO).pack(pady=(10, 0))

        cuerpo = tk.Frame(raiz, bg=BLANCO, padx=34)
        cuerpo.pack(fill="both", expand=True)

        tk.Label(cuerpo, text="Elige tu avatar", font=fuente(15, "bold"), bg=BLANCO,
                 fg=TEXTO).pack(pady=(20, 8))

        carrusel = tk.Frame(cuerpo, bg=BLANCO)
        carrusel.pack()
        estilo_flecha = dict(bg=BLANCO, fg=VERDE_OSCURO, hover=VERDE_SUAVE,
                             font=fuente(30, "bold"), padx=12, pady=0)
        Boton(carrusel, "‹", lambda: self._mover(-1), **estilo_flecha).grid(row=0, column=0, padx=6)
        self.lbl_grande = tk.Label(carrusel, bg=BLANCO, cursor="hand2")
        self.lbl_grande.grid(row=0, column=1, padx=8)
        Boton(carrusel, "›", lambda: self._mover(1), **estilo_flecha).grid(row=0, column=2, padx=6)

        self.lbl_contador = tk.Label(cuerpo, font=fuente(12), bg=BLANCO, fg=GRIS)
        self.lbl_contador.pack(pady=(6, 6))

        self.tira = tk.Frame(cuerpo, bg=BLANCO, height=0)
        self.tira.pack(fill="x")
        self.miniaturas = []
        visibles = min(7, self.avatares.total)
        contenedor = tk.Frame(self.tira, bg=BLANCO)
        contenedor.place(relx=0.5, rely=0.5, anchor="center")

        tk.Label(cuerpo, text="Nombre", font=fuente(13, "bold"), bg=BLANCO, fg=TEXTO,
                 anchor="w").pack(fill="x", pady=(16, 4))
        self.e_nombre = Entrada(cuerpo, ayuda="¿Cómo te llamas?")
        self.e_nombre.pack(fill="x", ipady=8)
        if self.datos_login:
            self.e_nombre.poner(self.datos_login[2])

        tk.Label(cuerpo, text="Servidor", font=fuente(11), bg=BLANCO, fg=GRIS,
                 anchor="w").pack(fill="x", pady=(12, 2))
        self.e_servidor = Entrada(cuerpo, ayuda="ip:puerto", font=fuente(12))
        self.e_servidor.pack(fill="x", ipady=4)
        self.e_servidor.poner(self.servidor_inicial)

        self.b_entrar = Boton(cuerpo, "Entrar", self._entrar, font=fuente(15, "bold"), pady=10)
        self.b_entrar.pack(fill="x", pady=(20, 6))
        self.lbl_error = tk.Label(cuerpo, text="", font=fuente(12), bg=BLANCO, fg=ROJO,
                                  wraplength=380, justify="center")
        self.lbl_error.pack()

        self.lbl_grande.bind("<Button-1>", lambda e: self._mover(1))
        self.e_nombre.bind("<Return>", lambda e: self._entrar())
        self.e_servidor.bind("<Return>", lambda e: self._entrar())
        self.bind("<Left>", lambda e: self._mover(-1) if not isinstance(self.focus_get(), tk.Entry) else None)
        self.bind("<Right>", lambda e: self._mover(1) if not isinstance(self.focus_get(), tk.Entry) else None)
        self._pintar_carrusel()
        self.after(100, self.e_nombre.focus_set)

    def _mover(self, paso):
        if self.vista != "login":
            return
        total = self.avatares.total
        self.seleccion = (self.seleccion - 1 + paso) % total + 1
        self._pintar_carrusel()

    def _elegir(self, numero):
        self.seleccion = numero
        self._pintar_carrusel()

    def _pintar_carrusel(self):
        total = self.avatares.total
        self.lbl_grande.configure(image=self.avatares.avatar(self.seleccion, 170, anillo=VERDE))
        self.lbl_contador.configure(text=f"{self.seleccion}/{total}")
        mitad = len(self.miniaturas) // 2
        for posicion, lbl in enumerate(self.miniaturas):
            desplazamiento = posicion - mitad
            numero = (self.seleccion - 1 + desplazamiento) % total + 1
            if desplazamiento == 0:
                imagen = self.avatares.avatar(numero, 56, anillo=VERDE_OSCURO)
            else:
                imagen = self.avatares.avatar(numero, 46 if abs(desplazamiento) == 1 else 38)
            lbl.configure(image=imagen)
            lbl.bind("<Button-1>", lambda e, n=numero: self._elegir(n))

    def _entrar(self):
        if not self.b_entrar.activo:
            return
        nombre = " ".join(self.e_nombre.valor().split())
        if not nombre:
            self.lbl_error.configure(text="Escribe tu nombre para entrar.")
            return
        if len(nombre) > MAX_NOMBRE:
            self.lbl_error.configure(text=f"El nombre puede tener máximo {MAX_NOMBRE} caracteres.")
            return
        servidor = self.e_servidor.valor() or SERVIDOR_POR_DEFECTO
        host, _, puerto = servidor.partition(":")
        try:
            port = int(puerto) if puerto else PUERTO_POR_DEFECTO
        except ValueError:
            self.lbl_error.configure(text="El servidor debe tener el formato ip:puerto")
            return
        self.servidor_inicial = f"{host}:{port}"
        self.lbl_error.configure(text="")
        self.b_entrar.habilitar(False, "Conectando…")
        self.datos_login = (host.strip(), port, nombre, self.seleccion)
        self.red.conectar(host.strip(), port, {"accion": "login", "nombre": nombre, "imagen": self.seleccion})

    # Chats
    def mostrar_principal(self):
        self._limpiar_ventana()
        self.unbind("<Left>")
        self.unbind("<Right>")
        self.vista = "chat"
        self.resizable(True, True)
        self.minsize(900, 580)
        ui.centrar(self, 1140, 740)

        # ---------------- Columna izquierda ----------------
        izq = tk.Frame(self, bg=BLANCO, width=360)
        izq.pack(side="left", fill="y")
        izq.pack_propagate(False)
        tk.Frame(self, bg=LINEA, width=1).pack(side="left", fill="y")
        der = tk.Frame(self, bg=FONDO_CHAT)
        der.pack(side="left", fill="both", expand=True)

        cab = tk.Frame(izq, bg=VERDE, height=66)
        cab.pack(fill="x")
        cab.pack_propagate(False)
        tk.Label(cab, image=self.avatares.avatar(self.yo["imagen"], 42), bg=VERDE).pack(side="left", padx=(14, 10))
        textos = tk.Frame(cab, bg=VERDE)
        textos.pack(side="left", fill="y", pady=12)
        tk.Label(textos, text=recortar(self.yo["nombre"], 22), font=fuente(15, "bold"), bg=VERDE,
                 fg=TEXTO, anchor="w").pack(fill="x")
        self.lbl_mi_estado = tk.Label(textos, text="En línea", font=fuente(11), bg=VERDE,
                                      fg=TEXTO_SOBRE_VERDE, anchor="w")
        self.lbl_mi_estado.pack(fill="x")
        Boton(cab, "+", self._menu_nuevo, bg=VERDE, hover=VERDE_HOVER, font=fuente(24, "bold"),
              padx=14, pady=0).pack(side="right", padx=8)

        self.banner = tk.Frame(izq, bg="#FFECEC")
        self.lbl_banner = tk.Label(self.banner, text="", bg="#FFECEC", fg=ROJO, font=fuente(12),
                                   wraplength=220, justify="left")
        self.lbl_banner.pack(side="left", padx=12, pady=8)
        Boton(self.banner, "Reconectar", self._reconectar, bg=BLANCO, fg=ROJO, hover="#FFF6F6",
              font=fuente(12, "bold"), padx=10, pady=4).pack(side="right", padx=10)

        self.fila_pestanas = tk.Frame(izq, bg=BLANCO, padx=12, pady=10)
        self.fila_pestanas.pack(fill="x")
        self.pestanas = {}
        for clave, texto in (("chats", "Chats"), ("canales", "Canales"), ("activos", "Activos")):
            b = Boton(self.fila_pestanas, texto, lambda c=clave: self._cambiar_pestana(c),
                      font=fuente(12, "bold"), padx=14, pady=5)
            b.pack(side="left", padx=(0, 6))
            self.pestanas[clave] = b

        self.e_buscar = Entrada(izq, ayuda="Buscar", font=fuente(13))
        self.e_buscar.pack(fill="x", padx=12, ipady=5)
        self.e_buscar.bind("<KeyRelease>", lambda e: self._render_lista())

        self.pie = tk.Frame(izq, bg=BLANCO)
        self.pie.pack(side="bottom", fill="x")
        self.lista = ListaScroll(izq, bg=BLANCO)
        self.lista.pack(fill="both", expand=True, pady=(8, 0))

        # ---------------- Columna derecha ----------------
        self.cab_chat = tk.Frame(der, bg=BLANCO, height=66)
        self.cab_chat.pack(fill="x")
        self.cab_chat.pack_propagate(False)
        self.lbl_chat_img = tk.Label(self.cab_chat, bg=BLANCO)
        self.lbl_chat_img.pack(side="left", padx=(16, 12))
        info = tk.Frame(self.cab_chat, bg=BLANCO)
        info.pack(side="left", fill="y", pady=12)
        self.lbl_chat_nombre = tk.Label(info, text="", font=fuente(15, "bold"), bg=BLANCO, fg=TEXTO, anchor="w")
        self.lbl_chat_nombre.pack(fill="x")
        self.lbl_chat_sub = tk.Label(info, text="", font=fuente(11), bg=BLANCO, fg=GRIS, anchor="w")
        self.lbl_chat_sub.pack(fill="x")
        self.acciones_chat = tk.Frame(self.cab_chat, bg=BLANCO)
        self.acciones_chat.pack(side="right", padx=12)
        tk.Frame(der, bg=LINEA, height=1).pack(fill="x")

        self.barra = tk.Frame(der, bg=BLANCO, height=70)
        self.barra.pack(side="bottom", fill="x")
        self.barra.pack_propagate(False)
        tk.Frame(der, bg=LINEA, height=1).pack(side="bottom", fill="x")
        self.e_msg = Entrada(self.barra, ayuda="Escribe un mensaje", font=fuente(14))
        self.b_enviar = Boton(self.barra, "➤", self._enviar, font=fuente(17, "bold"), padx=16, pady=6)
        self.lbl_solo_admin = tk.Label(self.barra, text="Solo el administrador puede publicar en este canal",
                                       font=fuente(12), bg=BLANCO, fg=GRIS)
        self.e_msg.bind("<Return>", lambda e: self._enviar())

        self.area = ListaScroll(der, bg=FONDO_CHAT)
        self.area.pack(fill="both", expand=True)
        self.area.canvas.bind("<Configure>", self._area_redimensionada, add="+")

        self._estilo_pestanas()
        self._render_lista()

    # ------------------------------------------------------------------
    # Columna izquierda: pestañas y listas
    # ------------------------------------------------------------------
    def _estilo_pestanas(self):
        otros = len([i for i in self.activos if i != self.yo["id"]])
        textos = {"chats": "Chats", "canales": "Canales", "activos": f"Activos ({otros})"}
        for clave, boton in self.pestanas.items():
            boton.configure(text=textos[clave])
            if clave == self.pestana:
                boton.colores(VERDE, TEXTO, VERDE_HOVER)
            else:
                boton.colores(CAMPO, GRIS, VERDE_SUAVE)

    def _cambiar_pestana(self, clave):
        self.pestana = clave
        self.e_buscar.limpiar()
        self._estilo_pestanas()
        self._render_lista()

    def _orden_chat(self, chat):
        ultimo = chat.get("ultimo")
        return (ultimo or {}).get("fecha") or chat.get("creado") or ""

    def _render_lista(self):
        if self.vista != "chat":
            return
        posicion = self.lista.canvas.yview()[0]
        self.lista.limpiar()
        for hijo in self.pie.winfo_children():
            hijo.destroy()
        filtro = self.e_buscar.valor().lower()

        if self.pestana == "activos":
            usuarios = sorted((u for u in self.activos.values() if u["id"] != self.yo["id"]),
                              key=lambda u: u["nombre"].lower())
            usuarios = [u for u in usuarios if filtro in u["nombre"].lower()]
            for u in usuarios:
                self._fila_usuario(u)
            if not usuarios:
                self._vacio("No hay nadie más conectado." if not filtro else "Sin resultados.")
            self._boton_pie("Crear grupo", self._dialogo_grupo)
        else:
            tipos = ("Canal",) if self.pestana == "canales" else ("Global", "Grupal", "Privado")
            chats = [c for c in self.chats.values() if c["tipo"] in tipos and filtro in c["nombre"].lower()]
            chats.sort(key=self._orden_chat, reverse=True)
            chats.sort(key=lambda c: c["tipo"] != "Global")  # el global siempre arriba
            for c in chats:
                self._fila_chat(c)
            if self.pestana == "canales":
                if not chats:
                    self._vacio("Aún no sigues ningún canal." if not filtro else "Sin resultados.")
                self._boton_pie("Explorar canales", self._dialogo_explorar, secundario="Crear canal",
                                comando2=self._dialogo_canal)
            else:
                if len(chats) <= 1 and not filtro:
                    self._vacio("Abre la pestaña Activos para escribirle a alguien\no crea un grupo.")
                self._boton_pie("Nuevo grupo", self._dialogo_grupo)
        self.lista.update_idletasks()
        self.lista._ajustar_region()
        self.lista.canvas.yview_moveto(posicion)

    def _vacio(self, texto):
        tk.Label(self.lista.interior, text=texto, font=fuente(12), bg=BLANCO, fg=GRIS,
                 justify="center").pack(pady=26)

    def _boton_pie(self, texto, comando, secundario=None, comando2=None):
        tk.Frame(self.pie, bg=LINEA, height=1).pack(fill="x")
        fila = tk.Frame(self.pie, bg=BLANCO, padx=12, pady=10)
        fila.pack(fill="x")
        Boton(fila, texto, comando, font=fuente(13, "bold"), pady=8).pack(side="left", fill="x", expand=True)
        if secundario:
            Boton(fila, secundario, comando2, bg=CAMPO, hover=VERDE_SUAVE, font=fuente(13, "bold"),
                  pady=8).pack(side="left", fill="x", expand=True, padx=(8, 0))

    def _fila_base(self, seleccionada=False):
        bg = VERDE_SUAVE if seleccionada else BLANCO
        fila = tk.Frame(self.lista.interior, bg=bg, height=72)
        fila.pack(fill="x")
        fila.pack_propagate(False)
        linea = tk.Frame(fila, bg=LINEA, height=1)
        linea.fondo_fijo = True
        linea.place(x=74, rely=1.0, y=-1, relwidth=1.0)
        return fila, bg

    def _vista_previa(self, chat) -> str:
        ultimo = chat.get("ultimo")
        if not ultimo:
            return {"Global": "Todos los usuarios conectados",
                    "Grupal": f"{chat['miembros']} miembros",
                    "Canal": f"{chat['miembros']} seguidores",
                    "Privado": "Toca para escribir"}.get(chat["tipo"], "")
        texto = ultimo["texto"]
        if ultimo["idUsuario"] == self.yo["id"]:
            return "Tú: " + texto
        if chat["tipo"] in ("Global", "Grupal"):
            return f"{ultimo['autor']}: {texto}"
        return texto

    def _fila_chat(self, chat):
        seleccionada = chat["id"] == self.actual
        fila, bg = self._fila_base(seleccionada)
        tk.Label(fila, image=self._imagen_chat(chat, 48), bg=bg).pack(side="left", padx=(14, 12))
        centro = tk.Frame(fila, bg=bg)
        centro.pack(side="left", fill="both", expand=True, pady=(14, 0), padx=(0, 14))
        no_leidos = self.no_leidos.get(chat["id"], 0)

        arriba = tk.Frame(centro, bg=bg)
        arriba.pack(fill="x")
        tk.Label(arriba, text=recortar(chat["nombre"], 24), font=fuente(14, "bold"), bg=bg,
                 fg=TEXTO).pack(side="left")
        hora = self._hora_corta((chat.get("ultimo") or {}).get("fecha"))
        tk.Label(arriba, text=hora, font=fuente(11, "bold" if no_leidos else "normal"), bg=bg,
                 fg=VERDE_OSCURO if no_leidos else GRIS).pack(side="right")

        abajo = tk.Frame(centro, bg=bg)
        abajo.pack(fill="x", pady=(3, 0))
        tk.Label(abajo, text=recortar(self._vista_previa(chat), 34), font=fuente(12), bg=bg,
                 fg=TEXTO if no_leidos else GRIS).pack(side="left")
        if no_leidos:
            globo = tk.Label(abajo, text=str(no_leidos) if no_leidos < 100 else "99+",
                             font=fuente(10, "bold"), bg=VERDE, fg=TEXTO, padx=6)
            globo.fondo_fijo = True
            globo.pack(side="right")

        ui.al_clic(fila, lambda: self.abrir(chat["id"]))
        if not seleccionada:
            ui.con_hover(fila, BLANCO, "#F7FAF7")

    def _fila_usuario(self, usuario):
        fila, bg = self._fila_base()
        tk.Label(fila, image=self.avatares.avatar(usuario["imagen"], 48), bg=bg).pack(side="left", padx=(14, 12))
        centro = tk.Frame(fila, bg=bg)
        centro.pack(side="left", fill="both", expand=True, pady=(15, 0))
        tk.Label(centro, text=recortar(usuario["nombre"], 26), font=fuente(14, "bold"), bg=bg,
                 fg=TEXTO, anchor="w").pack(fill="x")
        tk.Label(centro, text="● en línea", font=fuente(11), bg=bg, fg=VERDE_OSCURO,
                 anchor="w").pack(fill="x")
        tk.Label(fila, text="Mensaje ›", font=fuente(12, "bold"), bg=bg, fg=VERDE_OSCURO).pack(side="right", padx=14)
        ui.al_clic(fila, lambda: self.red.enviar({"accion": "crear_privado", "idUsuario": usuario["id"]}))
        ui.con_hover(fila, BLANCO, "#F7FAF7")

    # Columna derecha: chat abierto
    def abrir(self, id_chat):
        if id_chat not in self.chats or self.vista != "chat":
            return
        self.actual = id_chat
        self.no_leidos[id_chat] = 0
        self._actualizar_titulo()
        self._pintar_cabecera()
        self._pintar_barra()
        if id_chat not in self.mensajes:
            self.mensajes[id_chat] = None
            self.pendientes[id_chat] = []
            self.red.enviar({"accion": "abrir_chat", "idChat": id_chat})
        self._render_mensajes()
        self._render_lista()
        if self.e_msg.winfo_ismapped():
            self.e_msg.focus_set()

    def _pintar_cabecera(self):
        chat = self.chats.get(self.actual)
        for hijo in self.acciones_chat.winfo_children():
            hijo.destroy()
        if chat is None:
            return
        self.lbl_chat_img.configure(image=self._imagen_chat(chat, 42))
        self.lbl_chat_nombre.configure(text=recortar(chat["nombre"], 50))
        sub, color = "", GRIS
        soy_dueno = chat["idDueno"] == self.yo["id"]
        if chat["tipo"] == "Global":
            sub = f"{len(self.activos)} conectados ahora · todos los usuarios"
        elif chat["tipo"] == "Grupal":
            sub = f"Grupo · {chat['miembros']} miembros"
        elif chat["tipo"] == "Privado":
            if chat["idOtro"] in self.activos:
                sub, color = "en línea", VERDE_OSCURO
            else:
                sub = self._ultima_vez(self.visto.get(chat["idOtro"]) or chat.get("vistoOtro"))
        elif chat["tipo"] == "Canal":
            n = chat["miembros"]
            sub = f"Canal · {n} seguidor{'es' if n != 1 else ''}"
            if soy_dueno:
                sub += " · eres el administrador"
        self.lbl_chat_sub.configure(text=sub, fg=color)

        estilo = dict(bg=BLANCO, hover=VERDE_SUAVE, font=fuente(12, "bold"), padx=10, pady=5)
        if chat["tipo"] == "Grupal":
            Boton(self.acciones_chat, "Salir del grupo", lambda: self._salir(chat), fg=ROJO, **estilo).pack()
        elif chat["tipo"] == "Canal" and soy_dueno:
            Boton(self.acciones_chat, "Eliminar canal", lambda: self._eliminar_canal(chat), fg=ROJO, **estilo).pack()
        elif chat["tipo"] == "Canal":
            Boton(self.acciones_chat, "Dejar de seguir", lambda: self._salir(chat), fg=GRIS, **estilo).pack()

    def _pintar_barra(self):
        chat = self.chats.get(self.actual)
        for w in (self.e_msg, self.b_enviar, self.lbl_solo_admin):
            w.pack_forget()
        if chat and chat["tipo"] == "Canal" and chat["idDueno"] != self.yo["id"]:
            self.lbl_solo_admin.pack(expand=True)
        else:
            self.b_enviar.pack(side="right", padx=(0, 16))
            self.e_msg.pack(side="left", fill="x", expand=True, padx=(16, 10), pady=14, ipady=7)

    def _area_redimensionada(self, evento):
        nuevo = max(240, min(560, int(evento.width * 0.62)))
        if abs(nuevo - self.ancho_burbuja) > 30:
            self.ancho_burbuja = nuevo
            if getattr(self, "_rerender", None):
                self.after_cancel(self._rerender)
            self._rerender = self.after(150, self._render_mensajes)

    def _render_mensajes(self):
        self._rerender = None
        if self.vista != "chat":
            return
        self.area.limpiar()
        mensajes = self.mensajes.get(self.actual)
        if mensajes is None:
            tk.Label(self.area.interior, text="Cargando mensajes…", font=fuente(12), bg=FONDO_CHAT,
                     fg=GRIS).pack(pady=40)
            return
        if not mensajes:
            chat = self.chats.get(self.actual, {})
            if chat.get("tipo") == "Canal" and chat.get("idDueno") != self.yo["id"]:
                texto = "Este canal todavía no tiene publicaciones."
            elif chat.get("tipo") == "Canal":
                texto = "Tu canal está listo. Publica algo para tus seguidores."
            else:
                texto = "Todavía no hay mensajes. ¡Saluda!"
            tarjeta = tk.Label(self.area.interior, text=texto, font=fuente(12), bg=BLANCO, fg=GRIS,
                               padx=18, pady=10, highlightthickness=1, highlightbackground=LINEA)
            tarjeta.pack(pady=40)
            return
        tk.Frame(self.area.interior, bg=FONDO_CHAT, height=10).pack()
        anterior = None
        for m in mensajes:
            self._burbuja(m, anterior)
            anterior = m
        self.area.al_final()

    def _burbuja(self, m, anterior):
        chat = self.chats.get(self.actual, {})
        interior = self.area.interior
        fecha = self._fecha(m["fecha"]) or datetime.now()
        fecha_ant = self._fecha(anterior["fecha"]) if anterior else None

        if fecha_ant is None or fecha_ant.date() != fecha.date():
            sep = tk.Frame(interior, bg=FONDO_CHAT)
            sep.pack(fill="x", pady=(12, 6))
            tk.Label(sep, text=self._dia_bonito(fecha), font=fuente(11), bg=BLANCO, fg=GRIS,
                     padx=12, pady=3, highlightthickness=1, highlightbackground=LINEA).pack()
            anterior = None

        mio = m["idUsuario"] == self.yo["id"]
        seguido = (anterior is not None and anterior["idUsuario"] == m["idUsuario"]
                   and fecha_ant and (fecha - fecha_ant) < timedelta(minutes=5))
        estilo_grupo = chat.get("tipo") in ("Global", "Grupal")

        fila = tk.Frame(interior, bg=FONDO_CHAT)
        fila.pack(fill="x", padx=18, pady=(1 if seguido else 6, 0))
        if mio:
            burbuja = tk.Frame(fila, bg=VERDE, padx=12, pady=6)
            burbuja.pack(side="right")
            color_hora = TEXTO_SOBRE_VERDE
        else:
            if estilo_grupo:
                if seguido:
                    tk.Frame(fila, bg=FONDO_CHAT, width=40, height=1).pack(side="left")
                else:
                    tk.Label(fila, image=self.avatares.avatar(m["imagen"], 32),
                             bg=FONDO_CHAT).pack(side="left", anchor="n", padx=(0, 8))
            burbuja = tk.Frame(fila, bg=BLANCO, padx=12, pady=6, highlightthickness=1,
                               highlightbackground=LINEA)
            burbuja.pack(side="left")
            color_hora = GRIS_CLARO
        bg = burbuja.cget("bg")
        if not mio and estilo_grupo and not seguido:
            tk.Label(burbuja, text=m["nombre"], font=fuente(12, "bold"), bg=bg,
                     fg=ui.color_de_usuario(m["idUsuario"])).pack(anchor="w")
        tk.Label(burbuja, text=m["texto"], font=fuente(14), bg=bg, fg=TEXTO, justify="left",
                 wraplength=self.ancho_burbuja).pack(anchor="w")
        tk.Label(burbuja, text=fecha.strftime("%H:%M"), font=fuente(10), bg=bg,
                 fg=color_hora).pack(anchor="e")

    def _agregar_mensaje_visible(self, m):
        mensajes = self.mensajes.get(self.actual) or []
        if len(mensajes) <= 1:  # había un estado vacío: se pinta todo
            self._render_mensajes()
            return
        abajo = self.area.esta_al_final()
        self._burbuja(m, mensajes[-2])
        if abajo or m["idUsuario"] == self.yo["id"]:
            self.area.al_final()
        else:
            self.area.update_idletasks()
            self.area._ajustar_region()

    def _enviar(self):
        texto = self.e_msg.valor()
        if not texto or self.actual is None:
            return
        if len(texto) > MAX_MENSAJE:
            self.aviso(f"El mensaje es muy largo (máximo {MAX_MENSAJE} caracteres).")
            return
        if not self.red.enviar({"accion": "enviar", "idChat": self.actual, "texto": texto}):
            self.aviso("Sin conexión con el servidor.")
            return
        self.e_msg.delete(0, "end")

    def _salir(self, chat):
        pregunta = (f"¿Salir del grupo «{chat['nombre']}»?" if chat["tipo"] == "Grupal"
                    else f"¿Dejar de seguir «{chat['nombre']}»?")
        if messagebox.askyesno("Wasap", pregunta, parent=self):
            self.red.enviar({"accion": "salir_chat", "idChat": chat["id"]})

    def _eliminar_canal(self, chat):
        if messagebox.askyesno("Wasap", f"¿Eliminar el canal «{chat['nombre']}» para todos sus seguidores?",
                               icon="warning", parent=self):
            self.red.enviar({"accion": "eliminar_canal", "idChat": chat["id"]})

    def _actualizar_titulo(self):
        total = sum(n for i, n in self.no_leidos.items() if i in self.chats)
        self.title(f"({total}) Wasap" if total else "Wasap")

    # Menu
    def _menu_nuevo(self):
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Crear chat individual", command=lambda: self._cambiar_pestana("activos"))
        menu.add_command(label="Crear grupo", command=self._dialogo_grupo)
        menu.add_command(label="Crear canal", command=self._dialogo_canal)
        try:
            menu.tk_popup(self.winfo_pointerx(), self.winfo_pointery())
        finally:
            menu.grab_release()

    def _dialogo(self, titulo, ancho, alto):
        d = tk.Toplevel(self)
        d.title(titulo)
        d.configure(bg=BLANCO)
        d.resizable(False, False)
        d.transient(self)
        ui.centrar(d, ancho, alto, sobre=self)
        banda = tk.Frame(d, bg=VERDE, height=56)
        banda.pack(fill="x")
        banda.pack_propagate(False)
        tk.Label(banda, text=titulo, font=fuente(16, "bold"), bg=VERDE, fg=TEXTO).pack(side="left", padx=18)
        Boton(banda, "✕", d.destroy, bg=VERDE, hover=VERDE_HOVER, font=fuente(14, "bold"),
              padx=10, pady=2).pack(side="right", padx=8)
        d.bind("<Escape>", lambda e: d.destroy())

        def bloquear():  # el diálogo es modal; si aún no es visible, se reintenta
            try:
                d.grab_set()
            except tk.TclError:
                d.after(100, bloquear)
        d.after(50, bloquear)
        return d

    def _dialogo_grupo(self):
        candidatos = sorted((u for u in self.activos.values() if u["id"] != self.yo["id"]),
                            key=lambda u: u["nombre"].lower())
        d = self._dialogo("Nuevo grupo", 440, 600)
        cuerpo = tk.Frame(d, bg=BLANCO, padx=20)
        cuerpo.pack(fill="both", expand=True)
        tk.Label(cuerpo, text="Nombre del grupo", font=fuente(13, "bold"), bg=BLANCO, fg=TEXTO,
                 anchor="w").pack(fill="x", pady=(16, 4))
        e_nombre = Entrada(cuerpo, ayuda="Ej. Equipo de Sistemas Distribuidos")
        e_nombre.pack(fill="x", ipady=7)
        lbl_cuenta = tk.Label(cuerpo, text="Participantes · 0 seleccionados", font=fuente(13, "bold"),
                              bg=BLANCO, fg=TEXTO, anchor="w")
        lbl_cuenta.pack(fill="x", pady=(16, 6))

        pie = tk.Frame(d, bg=BLANCO, padx=20, pady=14)
        pie.pack(side="bottom", fill="x", before=cuerpo)
        lista = ListaScroll(cuerpo, bg=BLANCO, highlightthickness=1, highlightbackground=LINEA)
        lista.pack(fill="both", expand=True)

        seleccion = set()

        def alternar(id_usuario, marca):
            if id_usuario in seleccion:
                seleccion.discard(id_usuario)
                marca.configure(text="", bg=BLANCO, highlightbackground=GRIS_CLARO)
            else:
                seleccion.add(id_usuario)
                marca.configure(text="✓", bg=VERDE, highlightbackground=VERDE_OSCURO)
            lbl_cuenta.configure(text=f"Participantes · {len(seleccion)} seleccionado{'s' if len(seleccion) != 1 else ''}")

        for u in candidatos:
            fila = tk.Frame(lista.interior, bg=BLANCO, height=58)
            fila.pack(fill="x")
            fila.pack_propagate(False)
            tk.Label(fila, image=self.avatares.avatar(u["imagen"], 38), bg=BLANCO).pack(side="left", padx=12)
            tk.Label(fila, text=recortar(u["nombre"], 28), font=fuente(14), bg=BLANCO, fg=TEXTO).pack(side="left")
            marca = tk.Label(fila, text="", width=2, font=fuente(13, "bold"), bg=BLANCO, fg=TEXTO,
                             highlightthickness=2, highlightbackground=GRIS_CLARO)
            marca.fondo_fijo = True
            marca.pack(side="right", padx=14)
            ui.al_clic(fila, lambda i=u["id"], m=marca: alternar(i, m))
            ui.con_hover(fila, BLANCO, "#F7FAF7")
        if not candidatos:
            tk.Label(lista.interior, text="No hay nadie más conectado.\nLos grupos se forman con usuarios activos.",
                     font=fuente(12), bg=BLANCO, fg=GRIS, justify="center").pack(pady=30)

        lbl_error = tk.Label(pie, text="", font=fuente(11), bg=BLANCO, fg=ROJO)
        lbl_error.pack(fill="x")

        def crear():
            nombre = e_nombre.valor()
            if not nombre:
                lbl_error.configure(text="Escribe un nombre para el grupo.")
            elif len(nombre) > 100:
                lbl_error.configure(text="El nombre puede tener máximo 100 caracteres.")
            elif not seleccion:
                lbl_error.configure(text="Elige al menos a una persona.")
            else:
                self.red.enviar({"accion": "crear_grupo", "nombre": nombre, "miembros": sorted(seleccion)})
                d.destroy()

        botones = tk.Frame(pie, bg=BLANCO)
        botones.pack(fill="x", pady=(6, 0))
        Boton(botones, "Cancelar", d.destroy, bg=CAMPO, hover=VERDE_SUAVE).pack(side="left", fill="x", expand=True)
        Boton(botones, "Crear grupo", crear).pack(side="left", fill="x", expand=True, padx=(8, 0))
        e_nombre.focus_set()

    def _dialogo_canal(self):
        d = self._dialogo("Crear canal", 420, 330)
        cuerpo = tk.Frame(d, bg=BLANCO, padx=20)
        cuerpo.pack(fill="both", expand=True)
        tk.Label(cuerpo, text="Nombre del canal", font=fuente(13, "bold"), bg=BLANCO, fg=TEXTO,
                 anchor="w").pack(fill="x", pady=(18, 4))
        e_nombre = Entrada(cuerpo, ayuda="Ej. Avisos de la clase")
        e_nombre.pack(fill="x", ipady=7)
        tk.Label(cuerpo, text="Solo tú podrás publicar. Cualquiera puede encontrarlo en\n"
                              "«Explorar canales», seguirlo y leer tus publicaciones.",
                 font=fuente(11), bg=BLANCO, fg=GRIS, justify="left", anchor="w").pack(fill="x", pady=(10, 0))
        lbl_error = tk.Label(cuerpo, text="", font=fuente(11), bg=BLANCO, fg=ROJO)
        lbl_error.pack(fill="x", pady=(6, 0))

        def crear():
            nombre = e_nombre.valor()
            if not nombre:
                lbl_error.configure(text="Escribe un nombre para el canal.")
            elif len(nombre) > 100:
                lbl_error.configure(text="El nombre puede tener máximo 100 caracteres.")
            else:
                self.red.enviar({"accion": "crear_canal", "nombre": nombre})
                d.destroy()

        botones = tk.Frame(d, bg=BLANCO, padx=20, pady=16)
        botones.pack(side="bottom", fill="x", before=cuerpo)
        Boton(botones, "Cancelar", d.destroy, bg=CAMPO, hover=VERDE_SUAVE).pack(side="left", fill="x", expand=True)
        Boton(botones, "Crear canal", crear).pack(side="left", fill="x", expand=True, padx=(8, 0))
        e_nombre.bind("<Return>", lambda e: crear())
        e_nombre.focus_set()

    def _dialogo_explorar(self):
        d = self._dialogo("Explorar canales", 460, 560)
        lista = ListaScroll(d, bg=BLANCO)
        pie = tk.Frame(d, bg=BLANCO, padx=20, pady=14)
        pie.pack(side="bottom", fill="x")
        tk.Frame(d, bg=LINEA, height=1).pack(side="bottom", fill="x")
        lista.pack(fill="both", expand=True)
        tk.Label(lista.interior, text="Buscando canales…", font=fuente(12), bg=BLANCO, fg=GRIS).pack(pady=30)
        Boton(pie, "Crear mi propio canal", lambda: (d.destroy(), self._dialogo_canal())).pack(fill="x")
        self.dlg_canales = (d, lista)
        self.red.enviar({"accion": "explorar_canales"})

    def ev_canales(self, datos):
        if not self.dlg_canales or not self.dlg_canales[0].winfo_exists():
            return
        d, lista = self.dlg_canales
        lista.limpiar()
        canales = datos["lista"]
        if not canales:
            tk.Label(lista.interior, text="Todavía no hay canales.\n¡Crea el primero!", font=fuente(12),
                     bg=BLANCO, fg=GRIS, justify="center").pack(pady=30)
        for canal in canales:
            fila = tk.Frame(lista.interior, bg=BLANCO, height=70)
            fila.pack(fill="x")
            fila.pack_propagate(False)
            tk.Frame(fila, bg=LINEA, height=1).place(x=72, rely=1.0, y=-1, relwidth=1.0)
            tk.Label(fila, image=self.avatares.icono("Canal", 44), bg=BLANCO).pack(side="left", padx=(16, 12))
            textos = tk.Frame(fila, bg=BLANCO)
            textos.pack(side="left", fill="both", expand=True, pady=(14, 0))
            tk.Label(textos, text=recortar(canal["nombre"], 26), font=fuente(14, "bold"), bg=BLANCO,
                     fg=TEXTO, anchor="w").pack(fill="x")
            n = canal["seguidores"]
            tk.Label(textos, text=f"de {recortar(canal['dueno'] or '', 18)} · {n} seguidor{'es' if n != 1 else ''}",
                     font=fuente(11), bg=BLANCO, fg=GRIS, anchor="w").pack(fill="x")
            if canal["idDueno"] == self.yo["id"]:
                Boton(fila, "Tuyo · Abrir", lambda c=canal: (d.destroy(), self._ir_a_canal(c["id"])),
                      bg=CAMPO, hover=VERDE_SUAVE, font=fuente(12, "bold"), padx=10, pady=5).pack(side="right", padx=14)
            elif canal["siguiendo"]:
                Boton(fila, "Abrir", lambda c=canal: (d.destroy(), self._ir_a_canal(c["id"])),
                      bg=CAMPO, hover=VERDE_SUAVE, font=fuente(12, "bold"), padx=12, pady=5).pack(side="right", padx=14)
            else:
                Boton(fila, "Seguir", lambda c=canal: (d.destroy(), self.red.enviar(
                    {"accion": "seguir_canal", "idChat": c["id"]})),
                    font=fuente(12, "bold"), padx=14, pady=5).pack(side="right", padx=14)

    def _ir_a_canal(self, id_chat):
        self.pestana = "canales"
        self._estilo_pestanas()
        self.abrir(id_chat)

    # Desconexión server
    def _mostrar_banner(self, texto):
        self.lbl_banner.configure(text=texto)
        if not self.banner.winfo_ismapped():
            self.banner.pack(fill="x", after=self.banner.master.winfo_children()[0])
        self.lbl_mi_estado.configure(text="Sin conexión")

    def _reconectar(self):
        if self.datos_login:
            host, port, nombre, imagen = self.datos_login
            self._mostrar_banner("Reconectando…")
            self.red.conectar(host, port, {"accion": "login", "nombre": nombre, "imagen": imagen})

    # Eventos del servidor
    def ev_error_conexion(self, texto):
        if self.vista == "login":
            self.lbl_error.configure(text=texto)
            self.b_entrar.habilitar(True, "Entrar")
        else:
            self._mostrar_banner("No se pudo reconectar.")

    def ev_desconectado(self):
        if self.vista == "login":
            self.lbl_error.configure(text="El servidor cerró la conexión.")
            self.b_entrar.habilitar(True, "Entrar")
        else:
            self._mostrar_banner("Se perdió la conexión con el servidor.")

    def ev_error_login(self, datos):
        self.red.cerrar()
        if self.vista == "login":
            self.lbl_error.configure(text=datos.get("mensaje", "No se pudo iniciar sesión."))
            self.b_entrar.habilitar(True, "Entrar")
        else:
            self._mostrar_banner(datos.get("mensaje", "No se pudo reconectar."))

    def ev_bienvenida(self, datos):
        servidor = self._fecha_sin_desfase(datos.get("horaServidor"))
        if servidor:
            minutos = round((datetime.now() - servidor).total_seconds() / 900) * 15
            self.desfase = timedelta(minutes=minutos)
        anterior = self.actual
        self.yo = datos["usuario"]
        self.id_global = datos["idGlobal"]
        self.chats = {c["id"]: c for c in datos["chats"]}
        self.mensajes, self.pendientes, self.no_leidos = {}, {}, {}
        self.activos = {u["id"]: u for u in datos["usuarios"]}
        self.mostrar_principal()
        self.abrir(anterior if anterior in self.chats else self.id_global)

    @staticmethod
    def _fecha_sin_desfase(texto):
        try:
            return datetime.strptime(texto, "%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError):
            return None

    def ev_usuarios(self, datos):
        nuevos = {u["id"]: u for u in datos["lista"]}
        hora_servidor = (datetime.now() - self.desfase).strftime("%Y-%m-%d %H:%M:%S")
        for id_usuario in self.activos:
            if id_usuario not in nuevos:
                self.visto[id_usuario] = hora_servidor
        self.activos = nuevos
        if self.vista == "chat":
            self._estilo_pestanas()
            self._pintar_cabecera()
            self._pedir_lista()

    def ev_chat(self, datos):
        chat = datos["chat"]
        self.chats[chat["id"]] = chat
        if datos.get("abrir"):
            self.pestana = "canales" if chat["tipo"] == "Canal" else "chats"
            self._estilo_pestanas()
            self.abrir(chat["id"])
        else:
            if chat["id"] == self.actual:
                self._pintar_cabecera()
                self._pintar_barra()
            self._pedir_lista()

    def ev_chat_eliminado(self, datos):
        id_chat = datos["idChat"]
        nombre = self.chats.get(id_chat, {}).get("nombre")
        for estado in (self.chats, self.mensajes, self.pendientes, self.no_leidos):
            estado.pop(id_chat, None)
        if self.actual == id_chat:
            self.abrir(self.id_global)
            if nombre:
                self.aviso(f"«{nombre}» ya no está disponible.")
        self._actualizar_titulo()
        self._pedir_lista()

    def ev_historial(self, datos):
        id_chat = datos["idChat"]
        mensajes = datos["mensajes"]
        vistos = {m["id"] for m in mensajes}
        for m in self.pendientes.pop(id_chat, []):
            if m["id"] not in vistos:
                mensajes.append(m)
        mensajes.sort(key=lambda m: m["id"])
        self.mensajes[id_chat] = mensajes
        if id_chat == self.actual:
            self._render_mensajes()

    def ev_mensaje(self, datos):
        id_chat, m = datos["idChat"], datos["mensaje"]
        chat = self.chats.get(id_chat)
        if chat is None:
            return
        chat["ultimo"] = {"texto": m["texto"][:120], "autor": m["nombre"],
                          "idUsuario": m["idUsuario"], "fecha": m["fecha"]}
        if id_chat in self.mensajes:
            lista = self.mensajes[id_chat]
            if lista is None:  # el historial todavía no llega
                self.pendientes.setdefault(id_chat, []).append(m)
            elif all(x["id"] != m["id"] for x in lista[-20:]):
                lista.append(m)
                if id_chat == self.actual and self.vista == "chat":
                    self._agregar_mensaje_visible(m)
        if id_chat != self.actual and m["idUsuario"] != self.yo["id"]:
            self.no_leidos[id_chat] = self.no_leidos.get(id_chat, 0) + 1
            self._actualizar_titulo()
        self._pedir_lista()

    def ev_error(self, datos):
        self.aviso(datos.get("mensaje", "Error"))


def main():
    if len(sys.argv) >= 3:
        servidor = f"{sys.argv[1]}:{sys.argv[2]}"
    elif len(sys.argv) == 2:
        servidor = sys.argv[1] if ":" in sys.argv[1] else f"{sys.argv[1]}:{PUERTO_POR_DEFECTO}"
    else:
        servidor = SERVIDOR_POR_DEFECTO
    App(servidor).mainloop()


if __name__ == "__main__":
    main()
