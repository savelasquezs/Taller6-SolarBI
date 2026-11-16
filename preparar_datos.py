import hashlib
import json
import shutil
import sqlite3
import time
import urllib.request
import zipfile
from compression import zstd
from pathlib import Path

from helpers.configuracion import entorno

BASE = 'https://zenodo.org/records/21436223/files/'
ARCHIVOS = ('opencem-v1.0.0.sqlite.zst', 'opencem-v1.0.0-support.zip', 'README.md', 'LICENSE-DATA.txt')


def sha256(ruta):
    with open(ruta, 'rb') as entrada:
        return hashlib.file_digest(entrada, 'sha256').hexdigest()


def descargar(nombre, destino):
    ruta = destino / nombre
    temporal = ruta.with_suffix(ruta.suffix + '.part')
    for intento in range(4):
        try:
            solicitud = urllib.request.Request(BASE + nombre + '?download=1', headers={'User-Agent': 'SolarBI/1.0 academic'})
            with urllib.request.urlopen(solicitud, timeout=90) as respuesta, temporal.open('wb') as salida:
                shutil.copyfileobj(respuesta, salida, 1024 * 1024)
            temporal.replace(ruta)
            return ruta
        except (OSError, TimeoutError):
            if intento == 3:
                raise
            time.sleep(2 ** intento)


def inventariar(ruta):
    resultado = {}
    with sqlite3.connect(ruta.as_uri() + '?mode=ro&immutable=1', uri=True) as db:
        if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise ValueError('La integridad de SQLite falló')
        for (nombre,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
            tabla = '"' + nombre.replace('"', '""') + '"'
            columnas = [dict(zip(('cid', 'nombre', 'tipo', 'no_nulo', 'default', 'pk'), c))
                        for c in db.execute(f'PRAGMA table_info({tabla})')]
            item = {'filas': db.execute(f'SELECT count(*) FROM {tabla}').fetchone()[0], 'columnas': columnas}
            nombres = {c['nombre'] for c in columnas}
            if {'read_ts', 'inverter'} <= nombres:
                item['cobertura'] = db.execute(f'SELECT inverter,count(*),min(read_ts),max(read_ts) FROM {tabla} GROUP BY inverter').fetchall()
            if nombre == 'context':
                item['cobertura'] = db.execute('SELECT min(start),max(end),min(recorded),max(recorded) FROM context').fetchone()
            resultado[nombre] = item
    return resultado


def preparar():
    config = entorno()
    bronze = Path(config.get('DATA_DIR', 'D:/Datos/Taller6')) / 'bronze'
    informes = Path(config.get('OUTPUT_DIR', 'D:/Entregas/Taller6'))
    bronze.mkdir(parents=True, exist_ok=True)
    informes.mkdir(parents=True, exist_ok=True)
    sumas = descargar('opencem-v1.0.0-SHA256SUMS.txt', bronze)
    esperados = {}
    for linea in sumas.read_text(encoding='utf-8').splitlines():
        if linea.strip():
            digest, nombre = linea.split(maxsplit=1)
            esperados[Path(nombre.strip().lstrip('*')).name] = digest
    evidencia = {}
    for nombre in ARCHIVOS:
        ruta = bronze / nombre
        if not ruta.exists() or sha256(ruta) != esperados[nombre]:
            print('Descargando ' + nombre, flush=True)
            descargar(nombre, bronze)
        digest = sha256(ruta)
        if digest != esperados[nombre]:
            raise ValueError('Checksum incorrecto: ' + nombre)
        evidencia[nombre] = {'sha256': digest, 'bytes': ruta.stat().st_size}
        print('SHA-256 verificado: ' + nombre, flush=True)
    sqlite = bronze / 'opencem-v1.0.0.sqlite'
    with zipfile.ZipFile(bronze / 'opencem-v1.0.0-support.zip') as soporte:
        manifest = json.loads(soporte.read('opencem-v1.0.0/manifests/release_manifest.json'))
        original = next(e for e in manifest['entries'] if e['path'].endswith('opencem-v1.0.0.sqlite'))
        for nombre in ('column_dictionary.csv', 'column_dictionary.json', 'schema.sql', 'validation_results.json'):
            (bronze / nombre).write_bytes(soporte.read('opencem-v1.0.0/documentation/' + nombre))
    if not sqlite.exists() or sha256(sqlite) != original['sha256']:
        print('Descomprimiendo SQLite en D:', flush=True)
        temporal = sqlite.with_suffix('.sqlite.part')
        with zstd.open(bronze / ARCHIVOS[0], 'rb') as entrada, temporal.open('wb') as salida:
            shutil.copyfileobj(entrada, salida, 1024 * 1024)
        if sha256(temporal) != original['sha256']:
            raise ValueError('Checksum incorrecto de SQLite descomprimido')
        temporal.replace(sqlite)
    evidencia[sqlite.name] = {'sha256': original['sha256'], 'bytes': sqlite.stat().st_size}
    (informes / 'checksums.json').write_text(json.dumps(evidencia, indent=2), encoding='utf-8')
    inventario = inventariar(sqlite)
    (informes / 'inventario.json').write_text(json.dumps(inventario, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({n: v['filas'] for n, v in inventario.items()}), flush=True)


if __name__ == '__main__':
    preparar()
