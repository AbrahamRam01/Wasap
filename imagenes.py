"""
Carga de avatares e íconos para el cliente (requiere Pillow: pip3 install pillow).

Los avatares son las primeras 20 imágenes de la carpeta avatares/, en orden
alfabético. La posición define el idImagen que se guarda en la base de datos:
el primer archivo es el 1, el segundo el 2, etc. Todos los clientes deben tener
las mismas imágenes con los mismos nombres.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageOps, ImageTk

EXTENSIONES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
VERDE = (181, 255, 168)        # #B5FFA8
VERDE_OSCURO = (46, 125, 50)   # #2E7D32
ESCALA = 4                     # se dibuja 4 veces más grande y se reduce: bordes suaves


def _circulo(imagen: Image.Image, tam: int, anillo=None, grosor=0.06) -> Image.Image:
    """Recorta la imagen en círculo (con anillo de color opcional)."""
    grande = tam * ESCALA
    foto = imagen.resize((grande, grande), Image.LANCZOS)
    lienzo = Image.new("RGBA", (grande, grande), (0, 0, 0, 0))
    mascara = Image.new("L", (grande, grande), 0)
    dibujo = ImageDraw.Draw(mascara)
    if anillo:
        borde = int(grande * grosor)
        hueco = int(grande * grosor * 0.6)
        ImageDraw.Draw(lienzo).ellipse((0, 0, grande - 1, grande - 1), fill=anillo)
        interior = borde + hueco
        ImageDraw.Draw(lienzo).ellipse((borde, borde, grande - 1 - borde, grande - 1 - borde),
                                       fill=(255, 255, 255, 255))
        foto = imagen.resize((grande - 2 * interior,) * 2, Image.LANCZOS)
        mascara = Image.new("L", foto.size, 0)
        ImageDraw.Draw(mascara).ellipse((0, 0, foto.size[0] - 1, foto.size[1] - 1), fill=255)
        lienzo.paste(foto, (interior, interior), mascara)
    else:
        dibujo.ellipse((0, 0, grande - 1, grande - 1), fill=255)
        lienzo.paste(foto, (0, 0), mascara)
    return lienzo.resize((tam, tam), Image.LANCZOS)


def _cuadrada(ruta: Path, lado=360) -> Image.Image:
    """Abre la imagen, la endereza (EXIF), la recorta al centro en cuadrado y la reduce."""
    imagen = Image.open(ruta)
    if imagen.format == "JPEG":
        imagen.draft("RGB", (lado * 2, lado * 2))  # carga rápida de fotos grandes
    imagen = ImageOps.exif_transpose(imagen).convert("RGBA")
    return ImageOps.fit(imagen, (lado, lado), Image.LANCZOS)


def _icono(tipo: str, lado=360) -> Image.Image:
    """Íconos dibujados a mano para chats sin foto: Global, Grupal, Canal, Persona."""
    fondo = (209, 213, 219, 255) if tipo == "Persona" else VERDE + (255,)
    trazo = (255, 255, 255, 255) if tipo == "Persona" else VERDE_OSCURO + (255,)
    img = Image.new("RGBA", (lado, lado), fondo)
    d = ImageDraw.Draw(img)
    s = lado / 100  # coordenadas en una cuadrícula de 100x100
    g = int(5 * s)  # grosor de línea

    def caja(x0, y0, x1, y1):
        return (x0 * s, y0 * s, x1 * s, y1 * s)

    if tipo == "Global":
        d.ellipse(caja(24, 24, 76, 76), outline=trazo, width=g)
        d.ellipse(caja(38, 24, 62, 76), outline=trazo, width=g)
        d.line(caja(24, 50, 76, 50), fill=trazo, width=g)
        d.line(caja(29, 37, 71, 37), fill=trazo, width=int(g * .8))
        d.line(caja(29, 63, 71, 63), fill=trazo, width=int(g * .8))
    elif tipo == "Grupal":
        claro = (110, 175, 100, 255)
        d.ellipse(caja(54, 26, 74, 46), fill=claro)
        d.pieslice(caja(46, 50, 84, 88), 180, 360, fill=claro)
        d.ellipse(caja(28, 28, 50, 50), fill=trazo)
        d.pieslice(caja(18, 54, 60, 96), 180, 360, fill=trazo)
    elif tipo == "Canal":
        d.ellipse(caja(43, 43, 57, 57), fill=trazo)
        for r in (16, 28):
            d.arc(caja(50 - r, 50 - r, 50 + r, 50 + r), 135, 225, fill=trazo, width=g)
            d.arc(caja(50 - r, 50 - r, 50 + r, 50 + r), -45, 45, fill=trazo, width=g)
    else:  # Persona (avatar que falta)
        d.ellipse(caja(34, 20, 66, 52), fill=trazo)
        d.pieslice(caja(18, 58, 82, 122), 180, 360, fill=trazo)
    return img


class Avatares:
    def __init__(self, carpeta: Path, cantidad: int = 20):
        if not carpeta.is_dir():
            raise FileNotFoundError(f"No existe la carpeta {carpeta}")
        archivos = sorted((p for p in carpeta.iterdir()
                           if p.suffix.lower() in EXTENSIONES and not p.name.startswith(".")),
                          key=lambda p: p.name.lower())[:cantidad]
        if not archivos:
            raise FileNotFoundError(f"No hay imágenes en {carpeta}")
        self.archivos = archivos
        self._base = {}   # idImagen -> imagen cuadrada (PIL)
        self._cache = {}  # (clave, tam, anillo) -> PhotoImage (hay que guardar la referencia)

    @property
    def total(self) -> int:
        return len(self.archivos)

    def _imagen_base(self, numero: int) -> Image.Image:
        if numero not in self._base:
            try:
                self._base[numero] = _cuadrada(self.archivos[numero - 1])
            except Exception:
                self._base[numero] = _icono("Persona")  # archivo dañado
        return self._base[numero]

    def avatar(self, numero, tam: int, anillo=None) -> ImageTk.PhotoImage:
        """Foto circular del avatar `numero` (1..total); si no existe, una silueta."""
        valido = isinstance(numero, int) and 1 <= numero <= self.total
        clave = (numero if valido else "Persona", tam, anillo)
        if clave not in self._cache:
            base = self._imagen_base(numero) if valido else _icono("Persona")
            self._cache[clave] = ImageTk.PhotoImage(_circulo(base, tam, anillo))
        return self._cache[clave]

    def icono(self, tipo: str, tam: int) -> ImageTk.PhotoImage:
        """Ícono circular para 'Global', 'Grupal' o 'Canal'."""
        clave = ("icono:" + tipo, tam, None)
        if clave not in self._cache:
            self._cache[clave] = ImageTk.PhotoImage(_circulo(_icono(tipo), tam))
        return self._cache[clave]
