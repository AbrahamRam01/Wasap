"""
Cliente de chat distribuido (Tkinter + sockets TCP).

Uso:
    python3 cliente.py                      # usa HOST y PORT de abajo
    python3 cliente.py 127.0.0.1 3011       # para probar en local
"""

import queue
import socket
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

import protocolo

# ---------------- Configuración ----------------
HOST = "18.190.171.148"
PORT = 3011
BUFFER_SIZE = 1024
NUM_AVATARES = 20
CARPETA_AVATARES = Path(__file__).resolve().parent / "avatares"

# Colores de la interfaz
FONDO = "#1e1f26"
PANEL = "#2a2c36"
TEXTO = "#e8e8ee"
TENUE = "#9a9cab"
ACENTO = "#6c8cff"


class ClienteChat(tk.Tk):
    def __init__(self, host, port):
        super().__init__()
        self.host, self.port = host, port
        self.title("Chat distribuido")
        self.configure(bg=FONDO)
        self.minsize(460, 520)

        self.sock = None
        self.cola = queue.Queue()      # mensajes del hilo receptor -> interfaz
        self.conectado = False
        self.nombre = ""
        self.avatar = 0

        self._cargar_avatares()
        self.protocol("WM_DELETE_WINDOW", self.cerrar)
        self.mostrar_login()

    # ---------------- Avatares ----------------
    def _cargar_avatares(self):
        """Carga los 20 PNG en tamaño normal (64px) y chico (32px)."""
        self.img_grande = {}
        self.img_chica = {}
        for i in range(1, NUM_AVATARES + 1):
            ruta = CARPETA_AVATARES / f"avatar_{i:02d}.png"
            if not ruta.exists():
                messagebox.showerror("Falta una imagen", f"No se encontró {ruta}")
                sys.exit(1)
            img = tk.PhotoImage(file=str(ruta))
            self.img_grande[i] = img
            self.img_chica[i] = img.subsample(2, 2)
        # Avatar gris para quien no mandó uno (p. ej. alguien usando nc)
        gris = tk.PhotoImage(width=32, height=32)
        gris.put("#5a5c68", to=(0, 0, 32, 32))
        self.img_chica[0] = gris

    # ---------------- Pantalla de login ----------------
    def mostrar_login(self):
        self.marco = tk.Frame(self, bg=FONDO, padx=24, pady=20)
        self.marco.pack(fill="both", expand=True)

        tk.Label(self.marco, text="Chat distribuido", font=("Helvetica", 20, "bold"),
                 bg=FONDO, fg=TEXTO).pack(pady=(0, 2))
        tk.Label(self.marco, text=f"Servidor {self.host}:{self.port}",
                 bg=FONDO, fg=TENUE).pack(pady=(0, 16))

        tk.Label(self.marco, text="Tu nombre", bg=FONDO, fg=TEXTO,
                 anchor="w").pack(fill="x")
        self.entrada_nombre = tk.Entry(self.marco, font=("Helvetica", 14), bg=PANEL,
                                       fg=TEXTO, insertbackground=TEXTO, relief="flat")
        self.entrada_nombre.pack(fill="x", ipady=6, pady=(4, 16))
        self.entrada_nombre.focus()

        tk.Label(self.marco, text="Elige tu avatar", bg=FONDO, fg=TEXTO,
                 anchor="w").pack(fill="x")
        rejilla = tk.Frame(self.marco, bg=FONDO)
        rejilla.pack(pady=(6, 16))

        self.botones_avatar = {}
        for i in range(1, NUM_AVATARES + 1):
            b = tk.Label(rejilla, image=self.img_grande[i], bg=FONDO, bd=0,
                         highlightthickness=3, highlightbackground=FONDO, cursor="hand2")
            b.grid(row=(i - 1) // 5, column=(i - 1) % 5, padx=4, pady=4)
            b.bind("<Button-1>", lambda e, n=i: self.elegir_avatar(n))
            self.botones_avatar[i] = b

        self.boton_entrar = tk.Button(self.marco, text="Entrar al chat", command=self.entrar,
                                      font=("Helvetica", 14, "bold"), relief="flat",
                                      highlightbackground=ACENTO, padx=12, pady=6)
        self.boton_entrar.pack()
        self.entrada_nombre.bind("<Return>", lambda e: self.entrar())

    def elegir_avatar(self, n):
        if self.avatar:
            self.botones_avatar[self.avatar].config(highlightbackground=FONDO)
        self.avatar = n
        self.botones_avatar[n].config(highlightbackground=ACENTO)

    def entrar(self):
        nombre = self.entrada_nombre.get().strip()
        if not nombre:
            messagebox.showwarning("Falta tu nombre", "Escribe un nombre para entrar.")
            return
        if not self.avatar:
            messagebox.showwarning("Falta el avatar", "Elige una de las 20 imágenes.")
            return
        if len(nombre) > 20:
            nombre = nombre[:20]

        # Conectar al servidor
        try:
            self.sock = socket.create_connection((self.host, self.port), timeout=5)
            self.sock.settimeout(None)
        except OSError as e:
            messagebox.showerror("No se pudo conectar",
                                 f"No se pudo conectar a {self.host}:{self.port}\n\n{e}\n\n"
                                 "¿Está corriendo servidor.py?")
            return

        self.nombre = nombre
        self.conectado = True
        self.marco.destroy()
        self.mostrar_chat()

        threading.Thread(target=self._recibir, daemon=True).start()
        self.after(100, self._revisar_cola)

        # Registrar nombre+avatar y, un momento después, avisar a los demás.
        # (La pausa evita que el servidor lea los dos mensajes juntos.)
        self._enviar_crudo(protocolo.armar_nombre(nombre, self.avatar))
        self.after(250, lambda: self._enviar_crudo(
            protocolo.armar_aviso_entrada(nombre, self.avatar)))

    # ---------------- Pantalla de chat ----------------
    def mostrar_chat(self):
        encabezado = tk.Frame(self, bg=PANEL, padx=12, pady=8)
        encabezado.pack(fill="x")
        tk.Label(encabezado, image=self.img_chica[self.avatar], bg=PANEL).pack(side="left")
        tk.Label(encabezado, text=f"  {self.nombre}", font=("Helvetica", 14, "bold"),
                 bg=PANEL, fg=TEXTO).pack(side="left")
        self.estado = tk.Label(encabezado, text="● conectado", bg=PANEL, fg="#5fd38d")
        self.estado.pack(side="right")

        cuerpo = tk.Frame(self, bg=FONDO)
        cuerpo.pack(fill="both", expand=True, padx=10, pady=10)
        barra = tk.Scrollbar(cuerpo)
        barra.pack(side="right", fill="y")
        self.area = tk.Text(cuerpo, wrap="word", bg=FONDO, fg=TEXTO, relief="flat",
                            font=("Helvetica", 13), yscrollcommand=barra.set,
                            state="disabled", spacing1=4, spacing3=4, padx=6)
        self.area.pack(side="left", fill="both", expand=True)
        barra.config(command=self.area.yview)

        self.area.tag_config("nombre", font=("Helvetica", 13, "bold"), foreground=ACENTO)
        self.area.tag_config("yo", font=("Helvetica", 13, "bold"), foreground="#5fd38d")
        self.area.tag_config("sistema", foreground=TENUE, font=("Helvetica", 11, "italic"))

        abajo = tk.Frame(self, bg=PANEL, padx=10, pady=10)
        abajo.pack(fill="x")
        self.entrada_msg = tk.Entry(abajo, font=("Helvetica", 14), bg=FONDO, fg=TEXTO,
                                    insertbackground=TEXTO, relief="flat")
        self.entrada_msg.pack(side="left", fill="x", expand=True, ipady=6)
        self.entrada_msg.bind("<Return>", lambda e: self.enviar())
        self.entrada_msg.focus()
        tk.Button(abajo, text="Enviar", command=self.enviar, relief="flat",
                  highlightbackground=PANEL).pack(side="right", padx=(8, 0))

    def _agregar(self, *partes):
        """Agrega una línea al chat. Cada parte es (texto, tag) o una PhotoImage."""
        self.area.config(state="normal")
        for p in partes:
            if isinstance(p, tk.PhotoImage):
                self.area.image_create("end", image=p, padx=4)
            else:
                texto, tag = p
                self.area.insert("end", texto, tag)
        self.area.insert("end", "\n")
        self.area.config(state="disabled")
        self.area.see("end")

    def mostrar(self, evento):
        if evento["tipo"] == "mensaje":
            img = self.img_chica.get(evento["avatar"], self.img_chica[0])
            self._agregar(img, (f" {evento['nombre']}: ", "nombre"), (evento["texto"], None))
        elif evento["tipo"] == "entrada":
            self._agregar((f"→ {evento['nombre']} entró al chat", "sistema"))
        else:
            self._agregar((evento["texto"], "sistema"))

    # ---------------- Red ----------------
    def _enviar_crudo(self, texto):
        try:
            self.sock.sendall(texto.encode("utf-8"))
        except OSError:
            self._desconectado()

    def enviar(self):
        texto = self.entrada_msg.get().strip()
        if not texto or not self.conectado:
            return
        self.entrada_msg.delete(0, "end")
        self._enviar_crudo(texto)
        # El servidor no nos regresa nuestros propios mensajes, así que los mostramos aquí
        self._agregar(self.img_chica[self.avatar], (" Tú: ", "yo"), (texto, None))

    def _recibir(self):
        """Hilo aparte: lee del socket y pasa cada línea completa a la cola."""
        pendiente = ""
        while True:
            try:
                datos = self.sock.recv(BUFFER_SIZE)
            except OSError:
                datos = b""
            if not datos:
                self.cola.put(None)          # señal de desconexión
                return
            pendiente += datos.decode("utf-8", errors="replace")
            while "\n" in pendiente:
                linea, pendiente = pendiente.split("\n", 1)
                if linea.strip():
                    self.cola.put(linea)

    def _revisar_cola(self):
        """Tkinter no es thread-safe: la interfaz se actualiza solo desde aquí."""
        try:
            while True:
                linea = self.cola.get_nowait()
                if linea is None:
                    self._desconectado()
                    return
                self.mostrar(protocolo.interpretar(linea))
        except queue.Empty:
            pass
        self.after(100, self._revisar_cola)

    def _desconectado(self):
        if not self.conectado:
            return
        self.conectado = False
        self.estado.config(text="● desconectado", fg="#ff6b6b")
        self._agregar(("Se perdió la conexión con el servidor.", "sistema"))

    def cerrar(self):
        self.conectado = False
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
        self.destroy()


if __name__ == "__main__":
    host = sys.argv[1] if len(sys.argv) > 1 else HOST
    port = int(sys.argv[2]) if len(sys.argv) > 2 else PORT
    ClienteChat(host, port).mainloop()
