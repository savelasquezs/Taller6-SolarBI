import math
import re

CAMPOS = {'pv1power': 'solar_w', 'outw_a': 'carga_w', 'gridpowerw_a': 'red_w',
          'battvolt': 'bateria_v', 'battcurr': 'bateria_a', 'battsoc': 'soc'}
MAX_TS = 4102444800


def constante_json_invalida(valor):
    raise ValueError('Constante JSON no finita: '+valor)


def numero(valor):
    try:
        n = float(valor)
        return n if math.isfinite(n) else None
    except (ValueError, TypeError, OverflowError):
        return None


def limpiar_lectura(fila):
    ts = numero(fila['read_ts'])
    if ts is None or not 0 <= ts < MAX_TS or fila['inverter'] not in (1, 2):
        return None, ['clave_invalida']
    lectura = {'ts': ts, 'inversor': fila['inverter']}
    errores = []
    for original, nombre in CAMPOS.items():
        valor = numero(fila[original])
        if valor is not None and ((nombre in ('solar_w', 'carga_w', 'bateria_v') and valor < 0)
                                  or (nombre == 'soc' and not 0 <= valor <= 100)):
            valor = None
        if valor is None:
            errores.append(nombre + '_invalido')
        lectura[nombre] = valor
    v, a = lectura['bateria_v'], lectura['bateria_a']
    lectura['bateria_w'] = numero(v * a) if v is not None and a is not None else None
    if v is not None and a is not None and lectura['bateria_w'] is None:
        errores.append('bateria_w_invalido')
    lectura['valida'] = not errores
    lectura['errores'] = errores
    return lectura, errores


def contexto_publicable(valor):
    permitidas = ('source', 'context_type', 'device', 'inverter', 'task_type', 'textual_description')
    salida = {}
    for clave in permitidas:
        contenido = valor.get(clave)
        if isinstance(contenido, str):
            contenido = re.sub(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', '[correo omitido]', contenido)
            contenido = re.sub(r'(?i)(?:[a-z]:[\\/]|/home/|/users/)\S+', '[ruta omitida]', contenido)
            contenido = re.sub(r'(?i)(password|token|api[_-]?key|secret)\s*[:=]\s*\S+', r'\1=[omitido]', contenido)
        if isinstance(contenido, (str, int, float, bool)) or contenido is None:
            salida[clave] = contenido
    return salida
