import os
import sqlite3
from pathlib import Path

import psycopg
import pytest

from etl import ejecutar
from helpers.configuracion import conexion, entorno
from preparar_datos import sha256


@pytest.mark.skipif(not os.environ.get('POSTGRES_DB','').startswith('solarbi_test'),
                    reason='Requiere una base PostgreSQL de pruebas llamada solarbi_test*')
def test_carga_real_idempotente_y_json_invalido(tmp_path,monkeypatch):
    bronze=tmp_path/'bronze'
    bronze.mkdir()
    fuente=bronze/'opencem-v1.0.0.sqlite'
    with sqlite3.connect(fuente) as db:
        db.executescript('''CREATE TABLE analog_measurements(read_ts REAL,inverter INTEGER,pv1power REAL,
            outw_a REAL,gridpowerw_a REAL,battvolt REAL,battcurr REAL,battsoc REAL);
            CREATE TABLE context(id INTEGER,recorded INTEGER,start INTEGER,end INTEGER,value TEXT);
            CREATE TABLE statistics(read_ts REAL,inverter INTEGER,pvgeneratenergytoday REAL);''')
        for inversor in (1,2):
            for ts in (1767196800,1767196860):
                db.execute('INSERT INTO analog_measurements VALUES(?,?,?,?,?,?,?,?)',(ts,inversor,1000,600,100,50,-2,50))
            db.execute('INSERT INTO statistics VALUES(?,?,?)',(1767196860,inversor,0.02))
        db.execute('INSERT INTO context VALUES(1,1767196800,1767196800,1767196860,?)',('{"source":"prueba","inverter":1}',))
        db.execute('INSERT INTO context VALUES(2,1767196800,1767196800,1767196860,?)',('JSON roto',))
    monkeypatch.setenv('DATA_DIR',str(tmp_path))
    monkeypatch.setenv('OUTPUT_DIR',str(tmp_path/'salida'))
    original=sha256(fuente)
    ejecutar()
    def totales():
        with psycopg.connect(conexion(entorno())) as db:
            return db.execute('SELECT count(*),sum(lecturas),sum(solar_kwh),sum(bateria_carga_kwh) FROM gold.fact_energia').fetchone()
    antes=totales()
    assert antes[1]==4 and antes[2]==pytest.approx(2/60) and antes[3]==pytest.approx(2*100*60/3600000)
    with psycopg.connect(conexion(entorno())) as db:
        assert db.execute('SELECT count(*) FROM silver.contexto').fetchone()[0]==1
    ejecutar()
    assert totales()==antes and sha256(fuente)==original
