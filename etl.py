import argparse
import hashlib
import json
import math
import sqlite3
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from helpers.calidad import limpiar_lectura, contexto_publicable, numero
from helpers.configuracion import conexion, entorno
from helpers.energia import ENERGIAS, SUMAS, ZONA, acumulador, franja, integrar
from preparar_datos import sha256

RAIZ = Path(__file__).resolve().parent
LECTURAS = ('ts','inversor','solar_w','carga_w','red_w','bateria_v','bateria_a','bateria_w','soc','valida','errores')


def copiar(db, tabla, columnas, filas):
    if not filas:
        return
    consulta = sql.SQL('COPY {} ({}) FROM STDIN').format(sql.Identifier(*tabla.split('.')),
                sql.SQL(',').join(map(sql.Identifier, columnas)))
    with db.cursor().copy(consulta) as copia:
        for fila in filas:
            copia.write_row(fila)


def inicializar(config):
    with psycopg.connect(conexion(config)) as db:
        db.execute((RAIZ/'sql/01_modelo.sql').read_text(encoding='utf-8'))
        for nombre, clave in (('solarbi_bi','BI_PASSWORD'), ('solarbi_sim','SIM_PASSWORD')):
            if not db.execute('SELECT 1 FROM pg_roles WHERE rolname=%s',(nombre,)).fetchone():
                db.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {}').format(sql.Identifier(nombre),sql.Literal(config[clave])))
        db.execute('GRANT USAGE ON SCHEMA gold,demo TO solarbi_bi,solarbi_sim')
        db.execute('GRANT USAGE ON SCHEMA silver TO solarbi_bi,solarbi_sim')
        db.execute('GRANT SELECT ON ALL TABLES IN SCHEMA gold,demo TO solarbi_bi')
        db.execute('GRANT SELECT ON silver.ejecuciones TO solarbi_bi')
        db.execute('GRANT SELECT ON silver.lecturas TO solarbi_sim')
        db.execute('GRANT SELECT,INSERT,DELETE ON demo.lecturas TO solarbi_sim')
        db.execute('GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA demo TO solarbi_sim')


def fechas(db, fuente):
    limites=[]
    for tabla,columna in (('analog_measurements','read_ts'),('context','start'),('context','end')):
        limites.extend(x for x in fuente.execute(f'SELECT min("{columna}"),max("{columna}") FROM "{tabla}"').fetchone() if x is not None)
    desde=datetime.fromtimestamp(min(limites),ZONA).date()
    hasta=datetime.fromtimestamp(max(limites),ZONA).date()
    db.execute("""INSERT INTO gold.dim_fecha SELECT to_char(d,'YYYYMMDD')::INTEGER,d::DATE,
        extract(year FROM d),extract(month FROM d),to_char(d,'YYYY-MM'),extract(day FROM d),extract(isodow FROM d)
        FROM generate_series(%s::DATE,%s::DATE,interval '1 day') d ON CONFLICT DO NOTHING""",(desde,hasta))


def guardar_bloques(db, bloques, anteriores_a=float('inf')):
    claves=[clave for clave in bloques if clave[0]+300<=anteriores_a]
    filas=[]
    coberturas={'solar_kwh':'solar_s','carga_kwh':'carga_s','red_importada_kwh':'red_s',
                'red_exportada_kwh':'red_s','bateria_descarga_kwh':'bateria_s',
                'bateria_carga_kwh':'bateria_s','residual_kwh':'balance_s'}
    for clave in claves:
        r=bloques.pop(clave)
        fecha_id,franja_id=franja(r['ts'])
        valores=[None if k in ENERGIAS and r[coberturas[k]]==0 else
                 int(r[k]) if k in ('lecturas','lecturas_validas') else r[k] for k in SUMAS]
        filas.append((r['ts'],r['inversor'],fecha_id,franja_id,*valores))
    copiar(db,'gold.fact_energia',('ts','inversor','fecha_id','franja_id')+SUMAS,filas)


def cargar_lecturas(db, fuente, config, resumen, hasta=None):
    max_gap=float(config.get('MAX_GAP_SECONDS',120))
    umbral=float(config.get('SOC_THRESHOLD',20))
    consulta='SELECT read_ts,inverter,pv1power,outw_a,gridpowerw_a,battvolt,battcurr,battsoc FROM analog_measurements'
    argumentos=()
    if hasta is not None:
        consulta+=' WHERE read_ts<=?'
        argumentos=(hasta,)
    consulta+=' ORDER BY read_ts,inverter'
    previos,bloques={},{}
    filas=[]
    ultimo=None
    for fila in fuente.execute(consulta,argumentos):
        resumen['lecturas_origen']+=1
        r,errores=limpiar_lectura(fila)
        resumen.update(errores)
        if r is None:
            resumen['lecturas_rechazadas']+=1
            continue
        clave=(r['ts'],r['inversor'])
        if clave==ultimo:
            resumen['duplicados']+=1
            continue
        ultimo=clave
        filas.append(tuple(r[c] for c in LECTURAS))
        resumen['lecturas_cargadas']+=1
        resumen['lecturas_validas']+=int(r['valida'])
        clave_bloque=(math.floor(r['ts']/300)*300,r['inversor'])
        bloque=bloques.setdefault(clave_bloque,acumulador(*clave_bloque))
        bloque['lecturas']+=1
        bloque['lecturas_validas']+=int(r['valida'])
        previo=previos.get(r['inversor'])
        if previo:
            if r['ts']-previo['ts']>max_gap:
                resumen['huecos_mayores_120s']+=1
            for tramo in integrar(previo,r,max_gap,umbral):
                b=bloques.setdefault((tramo['ts'],tramo['inversor']),acumulador(tramo['ts'],tramo['inversor']))
                for k in SUMAS:
                    b[k]+=tramo[k]
        previos[r['inversor']]=r
        if len(filas)>=10000:
            copiar(db,'silver.lecturas',LECTURAS,filas)
            filas.clear()
            guardar_bloques(db,bloques,r['ts']-max_gap)
            if resumen['lecturas_cargadas']%250000==0:
                print(json.dumps({'lecturas':resumen['lecturas_cargadas']}),flush=True)
    copiar(db,'silver.lecturas',LECTURAS,filas)
    guardar_bloques(db,bloques)
    db.execute("""INSERT INTO gold.fact_energia
        SELECT g.ts,l.inversor,to_char(to_timestamp(g.ts) AT TIME ZONE 'Asia/Shanghai','YYYYMMDD')::INTEGER,
            (extract(hour FROM to_timestamp(g.ts) AT TIME ZONE 'Asia/Shanghai')*12+
            floor(extract(minute FROM to_timestamp(g.ts) AT TIME ZONE 'Asia/Shanghai')/5))::SMALLINT,
            NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,0,0,0,0,0,0,0,0,0,0
        FROM (SELECT inversor,min(ts) AS primero,max(ts) AS ultimo FROM silver.lecturas GROUP BY inversor) l
        CROSS JOIN LATERAL generate_series(
            extract(epoch FROM date_trunc('day',to_timestamp(l.primero) AT TIME ZONE 'Asia/Shanghai') AT TIME ZONE 'Asia/Shanghai'),
            extract(epoch FROM (date_trunc('day',to_timestamp(l.ultimo) AT TIME ZONE 'Asia/Shanghai')+interval '1 day') AT TIME ZONE 'Asia/Shanghai')-300,300) g(ts)
        ON CONFLICT DO NOTHING""")


def cargar_contexto(db, fuente, resumen):
    filas=[]
    eventos=[]
    tipos={}
    for fila in fuente.execute('SELECT * FROM context ORDER BY id'):
        resumen['contexto_origen']+=1
        try:
            valor=json.loads(fila['value'])
            if not isinstance(valor,dict):
                raise ValueError('JSON no objeto')
            tiempos=[numero(fila[c]) for c in ('recorded','start','end')]
            if any(t is None for t in tiempos) or tiempos[2]<tiempos[1]:
                raise ValueError('Intervalo inválido')
            fechas_utc=[datetime.fromtimestamp(t,timezone.utc) for t in tiempos]
            valor=contexto_publicable(valor)
            filas.append((fila['id'],*fechas_utc,Jsonb(valor)))
            tipo=str(valor.get('context_type') or 'Sin clasificar')[:200]
            tipos[tipo]=tipo
            inversor=valor.get('inverter')
            if inversor not in (1,2):
                inversor=0
            fecha_id,franja_id=franja(tiempos[1])
            eventos.append((f"ctx:{fila['id']}",inversor,fecha_id,franja_id,tipo,fechas_utc[1],fechas_utc[2],
                            str(valor.get('source') or 'Sin informar'),valor.get('textual_description')))
            resumen['contexto_cargado']+=1
        except (ValueError,TypeError,OverflowError,OSError):
            resumen['contexto_rechazado']+=1
    for tipo in tipos:
        db.execute('INSERT INTO gold.dim_tipo_evento VALUES(%s,%s) ON CONFLICT DO NOTHING',(tipo,tipo))
    copiar(db,'silver.contexto',('id','registrado','inicio','fin','valor'),filas)
    copiar(db,'gold.fact_eventos',('evento_id','inversor','fecha_id','franja_id','tipo','inicio','fin','fuente','descripcion'),eventos)


def eventos_bateria(db, config):
    db.execute("INSERT INTO gold.dim_tipo_evento VALUES('Batería baja','Episodio observado con SoC inferior al umbral') ON CONFLICT DO NOTHING")
    db.execute("""WITH anterior AS (
        SELECT *,lag(soc) OVER w AS previo,lag(ts) OVER w AS ts_previo
        FROM silver.lecturas WINDOW w AS(PARTITION BY inversor ORDER BY ts)
    ), grupos AS (
        SELECT *,sum(CASE WHEN soc<%s AND (previo IS NULL OR previo>=%s OR ts-ts_previo>%s) THEN 1 ELSE 0 END)
            OVER(PARTITION BY inversor ORDER BY ts) AS grupo FROM anterior
    ), episodios AS (
        SELECT inversor,grupo,min(ts) AS inicio,max(ts) AS fin
        FROM grupos WHERE soc<%s GROUP BY inversor,grupo
    ) INSERT INTO gold.fact_eventos
    SELECT 'soc:'||inversor||':'||inicio,inversor,
        to_char(to_timestamp(inicio) AT TIME ZONE 'Asia/Shanghai','YYYYMMDD')::INTEGER,
        (extract(hour FROM to_timestamp(inicio) AT TIME ZONE 'Asia/Shanghai')*12+
        floor(extract(minute FROM to_timestamp(inicio) AT TIME ZONE 'Asia/Shanghai')/5))::SMALLINT,
        'Batería baja',to_timestamp(inicio),to_timestamp(fin),'analog_measurements','SoC bajo observado, sin extender entre huecos'
    FROM episodios""",(float(config.get('SOC_THRESHOLD',20)),float(config.get('SOC_THRESHOLD',20)),
                         float(config.get('MAX_GAP_SECONDS',120)),float(config.get('SOC_THRESHOLD',20))))


def conciliar(db, fuente):
    registros=fuente.execute('''SELECT inverter,date(read_ts,'unixepoch','+8 hours') AS dia,
        max(pvgeneratenergytoday) AS kwh FROM statistics
        WHERE pvgeneratenergytoday>=0 GROUP BY inverter,dia''').fetchall()
    propios={ (r[0],r[1]):r[2:] for r in db.execute('''SELECT inversor,fecha::TEXT,sum(solar_kwh),sum(solar_s)/86400.0
        FROM gold.energia GROUP BY inversor,fecha''') }
    return [{'inversor':r['inverter'],'fecha':r['dia'],'contador_diario_max_kwh':r['kwh'],
             'integracion_observada_kwh':propios.get((r['inverter'],r['dia']),(None,None))[0],
             'cobertura_solar':propios.get((r['inverter'],r['dia']),(None,None))[1]}
            for r in registros]


def ejecutar(forzar=False, dias=None):
    config=entorno()
    bronze=Path(config.get('DATA_DIR','D:/Datos/Taller6'))/'bronze/opencem-v1.0.0.sqlite'
    salida=Path(config.get('OUTPUT_DIR','D:/Entregas/Taller6'))
    salida.mkdir(parents=True,exist_ok=True)
    digest=sha256(bronze)
    reglas=json.dumps({k:config.get(k) for k in ('MAX_GAP_SECONDS','SOC_THRESHOLD','PV_KWP','TARIFF_COP_KWH')},sort_keys=True)
    huella=hashlib.sha256((digest+reglas+str(dias)+'reglas-v1').encode()).hexdigest()
    inicializar(config)
    resumen=Counter()
    inicio=time.monotonic()
    with psycopg.connect(conexion(config)) as db, sqlite3.connect(bronze.as_uri()+'?mode=ro&immutable=1',uri=True) as fuente:
        fuente.row_factory=sqlite3.Row
        db.execute('SELECT pg_advisory_xact_lock(6006)')
        vigente=db.execute('SELECT huella FROM silver.ejecuciones WHERE fin IS NOT NULL ORDER BY fin DESC LIMIT 1').fetchone()
        if not forzar and vigente and vigente[0]==huella:
            print(json.dumps({'estado':'sin_cambios','huella':huella}),flush=True)
            return
        db.execute("SET LOCAL work_mem='8MB'")
        db.execute('TRUNCATE gold.fact_eventos,gold.fact_energia,silver.contexto,silver.lecturas')
        db.execute('INSERT INTO silver.ejecuciones(huella) VALUES(%s) ON CONFLICT(huella) DO UPDATE SET inicio=now(),fin=NULL',(huella,))
        for inv,nombre,carga in ((0,'Sin asociación','Contexto general'),(1,'Inversor 1','Estaciones de cómputo'),(2,'Inversor 2','Climatización y cargas asociadas')):
            db.execute('INSERT INTO gold.dim_inversor VALUES(%s,%s,%s,%s,%s) ON CONFLICT(inversor) DO UPDATE SET kwp=excluded.kwp',
                       (inv,nombre,carga,None if inv==0 else float(config.get('PV_KWP',12.48)),
                        'OpenCEM: un arreglo de 26 paneles × 480 W por subsistema; capacidad nominal de referencia'))
        db.execute('INSERT INTO gold.parametros VALUES(TRUE,%s,%s,%s,%s) ON CONFLICT(id) DO UPDATE SET tarifa_cop_kwh=excluded.tarifa_cop_kwh,max_gap_s=excluded.max_gap_s,soc_umbral=excluded.soc_umbral',
                   (float(config.get('TARIFF_COP_KWH',991.29)),'EPM octubre 2026, oficial/exento, nivel I, activos EPM; escenario colombiano',int(config.get('MAX_GAP_SECONDS',120)),float(config.get('SOC_THRESHOLD',20))))
        fechas(db,fuente)
        hasta=None if dias is None else fuente.execute('SELECT min(read_ts) FROM analog_measurements').fetchone()[0]+dias*86400
        cargar_lecturas(db,fuente,config,resumen,hasta)
        cargar_contexto(db,fuente,resumen)
        eventos_bateria(db,config)
        conciliacion=conciliar(db,fuente)
        resumen['bloques_gold']=db.execute('SELECT count(*) FROM gold.fact_energia').fetchone()[0]
        resumen['eventos_gold']=db.execute('SELECT count(*) FROM gold.fact_eventos').fetchone()[0]
        resumen['segundos_etl']=round(time.monotonic()-inicio,2)
        assert resumen['lecturas_origen']==resumen['lecturas_cargadas']+resumen['lecturas_rechazadas']+resumen['duplicados']
        assert resumen['contexto_origen']==resumen['contexto_cargado']+resumen['contexto_rechazado']
        db.execute('UPDATE silver.ejecuciones SET fin=clock_timestamp(),resumen=%s WHERE huella=%s',(Jsonb(dict(resumen)),huella))
    evidencia={'huella':huella,'sha256_bronze':digest,'resumen':dict(resumen),'alcance_dias':dias,
               'reglas':json.loads(reglas),'conciliacion':conciliacion}
    (salida/'etl_resultado.json').write_text(json.dumps(evidencia,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    print(json.dumps(dict(resumen),ensure_ascii=False),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--forzar',action='store_true')
    parser.add_argument('--dias',type=int)
    args=parser.parse_args()
    ejecutar(args.forzar,args.dias)
