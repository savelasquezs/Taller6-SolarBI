import json
import math
import sqlite3
from pathlib import Path

import pytest

from helpers.calidad import limpiar_lectura, contexto_publicable
from helpers.energia import integrar, area_positiva, franja, segundos_bajo


def lectura(ts, solar=1000, **valores):
    return {'ts': ts, 'inversor': 1, 'solar_w': solar, 'carga_w': 600,
            'red_w': 100, 'bateria_w': -50, 'soc': 50} | valores


def test_integracion_tiempo_real_y_limite_cinco_minutos():
    r = integrar(lectura(290), lectura(320, 2000))
    assert len(r) == 2
    assert sum(x['solar_kwh'] for x in r) == pytest.approx(1500 * 30 / 3600000)
    assert sum(x['registro_s'] for x in r) == 30
    assert r[0]['ts'] == 0 and r[1]['ts'] == 300


def test_medianoche_local_separa_dias():
    ts = 1767196800
    while franja(ts)[1] != 0:
        ts += 300
    r = integrar(lectura(ts - 10), lectura(ts + 10))
    assert len(r) == 2
    assert franja(r[0]['ts'])[0] != franja(r[1]['ts'])[0]


@pytest.mark.parametrize('delta', [0, -1, 121, 86400])
def test_no_interpolar_huecos_o_duplicados(delta):
    assert integrar(lectura(300), lectura(300 + delta)) == []


def test_faltante_solar_no_borra_energia_red():
    r = integrar(lectura(0, None), lectura(60))[0]
    assert r['solar_s'] == 0 and r['red_importada_kwh'] > 0
    assert r['balance_s'] == 0


def test_cambio_signo_no_duplica_carga_descarga():
    r = integrar(lectura(0, bateria_w=-100), lectura(60, bateria_w=100))[0]
    assert r['bateria_carga_kwh'] == pytest.approx(1500 / 3600000)
    assert r['bateria_descarga_kwh'] == pytest.approx(1500 / 3600000)


def test_soc_cruza_umbral():
    assert segundos_bajo(10, 30, 20, 60) == 30
    assert segundos_bajo(20, 20, 20, 60) == 0


def test_ceros_y_corriente_negativa_son_validos():
    r, errores = limpiar_lectura({'read_ts': 100, 'inverter': 1, 'pv1power': 0, 'outw_a': 0,
                                  'gridpowerw_a': 0, 'battvolt': 50, 'battcurr': -2, 'battsoc': 0})
    assert not errores and r['bateria_w'] == -100


def test_no_finitos_soc_y_claves():
    fila = {'read_ts': 100, 'inverter': 1, 'pv1power': math.inf, 'outw_a': 0,
            'gridpowerw_a': 0, 'battvolt': 50, 'battcurr': 2, 'battsoc': 101}
    r, errores = limpiar_lectura(fila)
    assert r['solar_w'] is None and r['soc'] is None and len(errores) == 2
    assert limpiar_lectura(fila | {'inverter': 3})[0] is None


def test_contexto_minimiza_datos_personales():
    r = contexto_publicable({'source': 'manual', 'password': 'secreto',
                             'textual_description': 'Persona a@b.com token=abc C:\\Users\\alguien\\x'})
    assert 'password' not in r
    assert 'a@b.com' not in json.dumps(r) and 'token=abc' not in json.dumps(r)
