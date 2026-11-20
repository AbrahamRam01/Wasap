# Wasap

Práctica 1 de Sistemas Distribuidos. 

# Ejecución

Instalar lo necesario:

```bash
pip3 install pymssql pillow
```

Crear un archivo `config_local.py` con el usuario de la base que utilizara:

```python
DB_USER = ""
DB_PASSWORD = ""
```

Ejecutar el cliente dentro de la carpeta donde esta el archivo "cliente.py":

```bash
python3 cliente.py 127.0.0.1 3011
```
