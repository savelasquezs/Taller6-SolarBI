import math
from datetime import datetime
from zoneinfo import ZoneInfo

ZONA = ZoneInfo('Asia/Shanghai')
ENERGIAS = ('solar_kwh', 'carga_kwh', 'red_importada_kwh', 'red_exportada_kwh',
            'bateria_descarga_kwh', 'bateria_carga_kwh', 'residual_kwh')
TIEMPOS = ('registro_s', 'solar_s', 'carga_s', 'red_s', 'bateria_s', 'soc_s', 'soc_bajo_s', 'balance_s')
SUMAS = ENERGIAS + TIEMPOS + ('soc_integral', 'lecturas', 'lecturas_validas')


def franja(ts):
    local = datetime.fromtimestamp(ts, ZONA)
    return int(local.strftime('%Y%m%d')), local.hour * 12 + local.minute // 5


def acumulador(ts, inversor):
    return {'ts': ts, 'inversor': inversor} | {k: 0.0 for k in SUMAS}


def area_positiva(a, b, segundos):
    if a >= 0 and b >= 0:
        return (a + b) * segundos / 2
    if a <= 0 and b <= 0:
        return 0.0
    positivo = max(a, b)
    return positivo * segundos * positivo / abs(b - a) / 2


def segundos_bajo(a, b, umbral, segundos):
    if a < umbral and b < umbral:
        return segundos
    if a >= umbral and b >= umbral:
        return 0.0
    return segundos * (umbral - min(a, b)) / abs(b - a)


def integrar(anterior, actual, max_hueco=120, umbral_soc=20):
    total = actual['ts'] - anterior['ts']
    if anterior['inversor'] != actual['inversor'] or not 0 < total <= max_hueco:
        return []
    inicio, fin = anterior['ts'], actual['ts']
    resultados = []
    while inicio < fin:
        bloque = math.floor(inicio / 300) * 300
        corte = min(fin, bloque + 300)
        dt = corte - inicio
        r = acumulador(bloque, actual['inversor'])
        r['registro_s'] = dt
        puntos = {}
        for campo in ('solar_w', 'carga_w', 'red_w', 'bateria_w', 'soc'):
            a, b = anterior[campo], actual[campo]
            if a is not None and b is not None:
                puntos[campo] = (a + (b - a) * (inicio - anterior['ts']) / total,
                                 a + (b - a) * (corte - anterior['ts']) / total)
        for campo, energia, cobertura in (('solar_w', 'solar_kwh', 'solar_s'), ('carga_w', 'carga_kwh', 'carga_s')):
            if campo in puntos:
                r[energia] = sum(puntos[campo]) * dt / 2 / 3600000
                r[cobertura] = dt
        for campo, positiva, negativa, cobertura in (
                ('red_w', 'red_importada_kwh', 'red_exportada_kwh', 'red_s'),
                ('bateria_w', 'bateria_descarga_kwh', 'bateria_carga_kwh', 'bateria_s')):
            if campo in puntos:
                a, b = puntos[campo]
                r[positiva] = area_positiva(a, b, dt) / 3600000
                r[negativa] = area_positiva(-a, -b, dt) / 3600000
                r[cobertura] = dt
        if 'soc' in puntos:
            a, b = puntos['soc']
            r['soc_integral'] = (a + b) * dt / 2
            r['soc_s'] = dt
            r['soc_bajo_s'] = segundos_bajo(a, b, umbral_soc, dt)
        if all(c in puntos for c in ('solar_w', 'carga_w', 'red_w', 'bateria_w')):
            r['balance_s'] = dt
            r['residual_kwh'] = (r['solar_kwh'] + r['red_importada_kwh'] + r['bateria_descarga_kwh']
                                  - r['carga_kwh'] - r['red_exportada_kwh'] - r['bateria_carga_kwh'])
        resultados.append(r)
        inicio = corte
    return resultados
