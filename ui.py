"""
Colores y widgets reutilizables del cliente.

En macOS los tk.Button ignoran el color de fondo, por eso los botones
son etiquetas (Label) con clic y efecto hover.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

# ---------------- Paleta: blanco + #B5FFA8 ----------------
VERDE = "#57B8D8"          # principal: cabeceras, burbujas propias, botones
VERDE_HOVER = "#366270"
VERDE_SUAVE = "#E9F6FF"    # chat seleccionado, fondos suaves
VERDE_OSCURO = "#2E507D"   # texto de acento sobre blanco
BLANCO = "#FFFFFF"
FONDO_CHAT = "#F4F8FA"
TEXTO = "#16211A"
GRIS = "#6B7280"
GRIS_CLARO = "#9CA3AF"
LINEA = "#E6EAE6"
ROJO = "#D93636"
CAMPO = "#F3F5F3"          # fondo de cajas de texto

# Colores para los nombres en los grupos (como WhatsApp)
COLORES_NOMBRE = ["#1E7B34", "#0B6E99", "#8E44AD", "#C0392B", "#B9770E",
                  "#117A65", "#2E4053", "#A93226", "#1F618D", "#7D3C98"]

FUENTE = "Helvetica"


def fuente(tam=13, peso="normal"):
    return (FUENTE, tam, peso)


def color_de_usuario(id_usuario) -> str:
    return COLORES_NOMBRE[(id_usuario or 0) % len(COLORES_NOMBRE)]


def recortar(texto: str, maximo: int) -> str:
    texto = " ".join(str(texto).split())
    return texto if len(texto) <= maximo else texto[: maximo - 1] + "…"


# ---------------- Utilidades de widgets ----------------
def descendientes(widget):
    yield widget
    for hijo in widget.winfo_children():
        yield from descendientes(hijo)


def al_clic(widget, funcion):
    """Hace clicable un widget y todos sus hijos."""
    for w in descendientes(widget):
        w.bind("<Button-1>", lambda e: funcion())
        try:
            w.configure(cursor="hand2")
        except tk.TclError:
            pass


def con_hover(fila, normal: str, encima: str):
    """Cambia el fondo de la fila (y sus hijos) al pasar el mouse, sin parpadeo."""
    def pintar(color):
        for w in descendientes(fila):
            if not getattr(w, "fondo_fijo", False):
                try:
                    w.configure(bg=color)
                except tk.TclError:
                    pass

    def salir(e):
        dentro = fila.winfo_containing(e.x_root, e.y_root)
        while dentro is not None:
            if dentro is fila:
                return
            dentro = dentro.master
        pintar(normal)

    for w in descendientes(fila):
        w.bind("<Enter>", lambda e: pintar(encima), add="+")
        w.bind("<Leave>", salir, add="+")


class Boton(tk.Label):
    """Botón plano con colores que sí funcionan en macOS."""

    def __init__(self, padre, texto, comando, bg=VERDE, fg=TEXTO, hover=VERDE_HOVER,
                 font=None, padx=16, pady=8, **kw):
        super().__init__(padre, text=texto, bg=bg, fg=fg, font=font or fuente(13, "bold"),
                         padx=padx, pady=pady, cursor="hand2", **kw)
        self._bg, self._fg, self._hover = bg, fg, hover
        self.comando = comando
        self.activo = True
        self.bind("<Enter>", lambda e: self.activo and self.configure(bg=self._hover))
        self.bind("<Leave>", lambda e: self.configure(bg=self._bg))
        self.bind("<ButtonRelease-1>", self._clic)

    def _clic(self, evento):
        dentro = 0 <= evento.x <= self.winfo_width() and 0 <= evento.y <= self.winfo_height()
        if self.activo and dentro and self.comando:
            self.comando()

    def colores(self, bg, fg, hover):
        self._bg, self._fg, self._hover = bg, fg, hover
        self.configure(bg=bg, fg=fg if self.activo else GRIS_CLARO)

    def habilitar(self, si: bool, texto=None):
        self.activo = si
        self.configure(fg=self._fg if si else GRIS_CLARO, cursor="hand2" if si else "arrow")
        if texto is not None:
            self.configure(text=texto)


class Entrada(tk.Entry):
    """Caja de texto con texto de ayuda (placeholder) y borde de color al enfocar."""

    def __init__(self, padre, ayuda="", font=None, bg=CAMPO, **kw):
        super().__init__(padre, font=font or fuente(14), bg=bg, fg=TEXTO, relief="flat",
                         insertbackground=TEXTO, highlightthickness=2,
                         highlightbackground=bg, highlightcolor=VERDE, **kw)
        self.ayuda = ayuda
        self._mostrando_ayuda = False
        self.bind("<FocusIn>", self._quitar_ayuda)
        self.bind("<FocusOut>", self._poner_ayuda)
        self._poner_ayuda()

    def _poner_ayuda(self, e=None):
        if not super().get() and self.ayuda:
            self._mostrando_ayuda = True
            self.configure(fg=GRIS_CLARO)
            self.insert(0, self.ayuda)

    def _quitar_ayuda(self, e=None):
        if self._mostrando_ayuda:
            self._mostrando_ayuda = False
            self.delete(0, "end")
            self.configure(fg=TEXTO)

    def valor(self) -> str:
        return "" if self._mostrando_ayuda else super().get().strip()

    def poner(self, texto: str):
        self._quitar_ayuda()
        self.delete(0, "end")
        self.insert(0, texto)

    def limpiar(self):
        self.delete(0, "end")
        if self.focus_get() is not self:
            self._poner_ayuda()


class ListaScroll(tk.Frame):
    """Marco con scroll vertical. Los widgets van dentro de .interior"""

    def __init__(self, padre, bg=BLANCO, **kw):
        super().__init__(padre, bg=bg, **kw)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0, yscrollincrement=12)
        self._resto = 0.0  # scroll acumulado del trackpad (Tk 9)
        self.barra = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.interior = tk.Frame(self.canvas, bg=bg)
        self._ventana = self.canvas.create_window((0, 0), window=self.interior, anchor="nw")
        self.canvas.configure(yscrollcommand=self.barra.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.barra.pack(side="right", fill="y")
        self.interior.bind("<Configure>", self._ajustar_region)
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._ventana, width=e.width))

    def _ajustar_region(self, e=None):
        self.canvas.configure(scrollregion=(0, 0, self.interior.winfo_reqwidth(),
                                            max(self.interior.winfo_reqheight(), self.canvas.winfo_height())))

    def limpiar(self):
        for hijo in self.interior.winfo_children():
            hijo.destroy()
        self.canvas.yview_moveto(0)

    def al_final(self):
        self.update_idletasks()
        self._ajustar_region()
        self.canvas.yview_moveto(1.0)

    def esta_al_final(self) -> bool:
        return self.canvas.yview()[1] > 0.98

    def rueda(self, evento, pixeles=None):
        """Mueve la lista. Funciona con mouse y trackpad en Tk 8.6 y Tk 9, en Mac, Windows y Linux."""
        if self.canvas.yview() == (0.0, 1.0):
            return
        if pixeles is not None:                    # trackpad en Tk 9 (TouchpadScroll)
            self._resto += -pixeles / 12
            pasos = int(self._resto)
            self._resto -= pasos
        elif getattr(evento, "num", None) == 4:    # Linux
            pasos = -3
        elif getattr(evento, "num", None) == 5:
            pasos = 3
        elif abs(evento.delta) >= 120:             # Windows, y Mac con Tk 9
            pasos = -int(evento.delta / 120) * 3
        else:                                      # Mac con Tk 8.6
            pasos = -evento.delta
        if pasos:
            self.canvas.yview_scroll(pasos, "units")


def instalar_rueda(raiz):
    """Una sola escucha global de la rueda: hace scroll en la lista bajo el puntero."""
    def lista_bajo_puntero(evento):
        w = raiz.winfo_containing(evento.x_root, evento.y_root)
        while w is not None and not isinstance(w, ListaScroll):
            w = w.master
        return w

    def girar(evento):
        lista = lista_bajo_puntero(evento)
        if lista is not None:
            lista.rueda(evento)

    def trackpad(evento):  # Tk 9: delta trae dx en los 16 bits altos y dy en los bajos
        lista = lista_bajo_puntero(evento)
        if lista is not None:
            dy = evento.delta & 0xFFFF
            if dy >= 0x8000:
                dy -= 0x10000
            lista.rueda(evento, pixeles=dy)

    raiz.bind_all("<MouseWheel>", girar)
    raiz.bind_all("<Button-4>", girar)
    raiz.bind_all("<Button-5>", girar)
    try:
        raiz.bind_all("<TouchpadScroll>", trackpad)  # solo existe en Tk 9
    except tk.TclError:
        pass


def centrar(ventana, ancho, alto, sobre=None):
    ventana.update_idletasks()
    if sobre is not None:
        x = sobre.winfo_rootx() + (sobre.winfo_width() - ancho) // 2
        y = sobre.winfo_rooty() + (sobre.winfo_height() - alto) // 3
    else:
        x = (ventana.winfo_screenwidth() - ancho) // 2
        y = (ventana.winfo_screenheight() - alto) // 3
    ventana.geometry(f"{ancho}x{alto}+{max(x, 0)}+{max(y, 0)}")
