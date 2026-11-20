# Wasap

Práctica 1 de Sistemas Distribuidos.

El servidor ya está corriendo en AWS (`3.149.102.2:3011`) y guarda todo en la base de datos, así que solo hay que ejecutar el cliente.

## Cómo ejecutarlo

1. Descargar o clonar el repositorio:

```bash
git clone https://github.com/AbrahamRam01/Wasap.git
cd Wasap
```

2. Instalar Pillow (para las imágenes):

```bash
pip3 install pillow
```

3. Ejecutar el cliente:

```bash
python3 cliente.py
```

En Windows es `pip install pillow` y `python cliente.py`.

## Uso

- Escribir un nombre y elegir un avatar.
- Al entrar aparece el chat global.
- En **Activos** se ve quién está conectado y se puede abrir un chat individual.
- Con el botón **+** se pueden crear grupos y canales.
- En **Canales** se pueden buscar y seguir canales.
