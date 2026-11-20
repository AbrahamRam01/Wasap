"""
Configuración del servidor.

Cada valor se puede cambiar con una variable de entorno, sin tocar el código:

    DB_PASSWORD='secreto' DB_NAME='MiBase' python3 server.py

Nunca escribas contraseñas reales en este archivo: se sube a git.
Ponlas en config_local.py (está en .gitignore), que sobrescribe estos valores.
"""

import os

# ---------------- Servidor de sockets ----------------
HOST = os.getenv("CHAT_HOST", "0.0.0.0")
PORT = int(os.getenv("CHAT_PORT", "3011"))

# ---------------- Base de datos (SQL Server) ----------------
DB_HOST = os.getenv("DB_HOST", "3.149.102.2")
DB_PORT = int(os.getenv("DB_PORT", "1433"))
DB_USER = os.getenv("DB_USER", "sa")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
# Nombre de la base que ya existe en el servidor (la que tiene las tablas).
DB_NAME = os.getenv("DB_NAME", "teletubbies")

# ---------------- Reglas del chat ----------------
NUM_IMAGENES = 20          # avatares disponibles (idImagen va de 1 a 20)
MAX_NOMBRE = 50            # Usuario.nombreCompleto es VARCHAR(50)
MAX_NOMBRE_CHAT = 100      # Chat.nombreChat es VARCHAR(100)
MAX_MENSAJE = 4000         # límite por mensaje para no saturar el socket
HISTORIAL = 150            # mensajes que se cargan al abrir un chat
NOMBRE_CHAT_GLOBAL = "Chat Global"


# ---------------- Valores privados ----------------
# config_local.py no se sube a git: ahí van el usuario y la contraseña reales.
try:
    from config_local import *  # noqa: F401,F403
except ImportError:
    pass
