# Chat distribuido con sockets en Python

Práctica de **Sistemas Distribuidos**. Es un chat global en el que varios clientes, desde distintas computadoras, se conectan por **sockets TCP** a un servidor que corre en una máquina remota (AWS). El servidor reenvía cada mensaje a todos los demás clientes conectados.

```
[Cliente A] ──┐
[Cliente B] ──┼──►  server.py  (18.190.171.148:3011)
[Cliente C] ──┘        reenvía cada mensaje a los demás
```

## Estructura

| Archivo / carpeta | Qué hace |
|---|---|
| `server.py` | Servidor TCP con un hilo por cliente. Guarda nombres y hace *broadcast* de los mensajes. |
| `cliente.py` | Cliente con interfaz gráfica (Tkinter): pantalla de login (nombre y avatar) y chat global. |
| `protocolo.py` | Funciones para armar e interpretar los mensajes que viajan por el socket. |
| `avatares/` | Las 20 imágenes predefinidas (`avatar_01.png` … `avatar_20.png`, 64×64 px). |

## Requisitos

- Python 3.9 o superior, tanto en el servidor como en el cliente.
- Tkinter en la computadora del cliente. El Python de python.org ya lo incluye. Si instalaste Python con Homebrew en macOS, agrégalo con `brew install python-tk`.
- No se necesitan librerías externas.

Para comprobar que Tkinter está disponible:
```bash
python3 -m tkinter
```
Debe abrirse una ventana pequeña de prueba.

## Cómo ejecutarlo

### 1. Servidor (en la máquina remota)

```bash
# desde tu computadora: subir el servidor
scp -i ADSO.pem server.py <usuario>@18.190.171.148:~/

# entrar al servidor y ejecutarlo
ssh -i ADSO.pem <usuario>@18.190.171.148
python3 server.py
```

Debe mostrar `Escuchando conexiones en: ('0.0.0.0', 3011)`.

Para que el servidor siga corriendo después de cerrar la sesión SSH:
```bash
nohup python3 server.py > server.log 2>&1 &
```

### 2. Cliente (en tu computadora)

```bash
python3 cliente.py                    # se conecta a 18.190.171.148:3011
python3 cliente.py 127.0.0.1 3011     # para pruebas locales
```

1. Escribe tu nombre.
2. Elige uno de los 20 avatares.
3. Presiona **Entrar al chat**.

Para probarlo, abre dos o más clientes (en la misma computadora o en varias) y escribe mensajes.

También puedes conectarte sin interfaz gráfica para depurar:
```bash
nc 18.190.171.148 3011
```

## Protocolo

El servidor reconoce tres tipos de mensaje de texto (UTF-8):

| El cliente envía | El servidor hace |
|---|---|
| `<name>Nombre\|07` | Guarda `Nombre\|07` como nombre del cliente. |
| `<command>join\|Nombre\|07` | Lo reenvía tal cual a los demás (aviso de "X entró al chat"). |
| `hola a todos` | Lo reenvía a los demás como `<Nombre\|07> hola a todos`. |

Para mandar el avatar **sin modificar el servidor**, el cliente lo agrega al nombre después de un `|`. Al recibir `<Abraham|07> hola`, el cliente separa el nombre (`Abraham`), el número de avatar (`7`) y el texto, y muestra la imagen `avatares/avatar_07.png` junto al mensaje.

Cada mensaje que reenvía el servidor termina en `\n`. El cliente junta lo que recibe y lo separa por líneas, porque TCP es un flujo de bytes: un mismo `recv()` puede traer medio mensaje o varios mensajes juntos.

## Detalles de implementación

- **Servidor:** crea un hilo (`threading.Thread`) por cliente. Cuando `recv()` regresa vacío, el cliente se desconectó: se quita de la lista y se cierra su socket.
- **Cliente:** un hilo aparte recibe los mensajes del socket y los pone en una `queue.Queue`. La interfaz revisa esa cola cada 100 ms con `after()`, porque Tkinter no es seguro para usarse desde varios hilos.
- El servidor no le regresa a cada cliente sus propios mensajes, así que el cliente los muestra localmente como "Tú".

## Puertos asignados

Tengo asignado el rango **3011–3020**. El servidor usa el **3011** por defecto. Para usar otro puerto, cambia `port` en `server.py` y pásalo al cliente: `python3 cliente.py 18.190.171.148 3012`.

## Seguridad

La llave `ADSO.pem` **no se sube al repositorio**: está excluida en `.gitignore`.
