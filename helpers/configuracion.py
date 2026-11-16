import os
from pathlib import Path


def entorno():
    ruta = Path(__file__).resolve().parents[1] / '.env'
    valores = {}
    if ruta.exists():
        for linea in ruta.read_text(encoding='utf-8-sig').splitlines():
            if '=' in linea and not linea.lstrip().startswith('#'):
                clave, valor = linea.split('=', 1)
                valores[clave.strip()] = valor.strip().strip('"').strip("'")
    return valores | dict(os.environ)


def conexion(config, usuario=None):
    from psycopg.conninfo import make_conninfo
    return make_conninfo(host=config.get('PGHOST', '127.0.0.1'),
                         port=config.get('PGPORT', config.get('DB_PORT', '55441')),
                         dbname=config.get('POSTGRES_DB', 'solarbi'),
                         user=usuario or config.get('POSTGRES_USER', 'solarbi'),
                         password=config['SIM_PASSWORD'] if usuario == 'solarbi_sim' else config['POSTGRES_PASSWORD'])
