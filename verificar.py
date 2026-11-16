import argparse
import base64
import json
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import psycopg

from helpers.configuracion import conexion, entorno


def api(config,ruta,contenido=None):
    auth=base64.b64encode(('admin:'+config['GRAFANA_PASSWORD']).encode()).decode()
    solicitud=urllib.request.Request('http://127.0.0.1:'+config.get('GRAFANA_PORT','3003')+ruta,
        headers={'Authorization':'Basic '+auth,'Content-Type':'application/json'},
        data=None if contenido is None else json.dumps(contenido).encode())
    with urllib.request.urlopen(solicitud,timeout=120) as respuesta:
        return json.load(respuesta)


def verificar(alertas=False):
    config=entorno()
    lectura=config|{'POSTGRES_USER':'solarbi_bi','POSTGRES_PASSWORD':config['BI_PASSWORD']}
    resultado={'fecha':datetime.now(timezone.utc).isoformat()}
    with psycopg.connect(conexion(lectura)) as db:
        resultado['totales']=db.execute('''SELECT inversor,count(*),sum(lecturas),sum(lecturas_validas),
            sum(solar_kwh),sum(carga_kwh),sum(red_importada_kwh),sum(registro_s)/(count(*)*300.0),
            sum(bateria_descarga_kwh),sum(soc_bajo_s)/nullif(sum(soc_s),0)
            FROM gold.fact_energia GROUP BY inversor ORDER BY inversor''').fetchall()
        assert sum(r[2] for r in resultado['totales'])==2989759,'No es el histórico completo'
        assert db.execute('SELECT count(*) FROM gold.fact_eventos WHERE evento_id LIKE %s',('ctx:%',)).fetchone()[0]==25178
        assert db.execute('''SELECT count(*) FROM gold.fact_energia WHERE registro_s<0 OR registro_s>300.00001
            OR solar_s>registro_s+0.00001 OR lecturas_validas>lecturas OR soc_bajo_s>soc_s+0.00001''').fetchone()[0]==0
        assert db.execute('SELECT count(*) FROM gold.fact_energia WHERE solar_s=0 AND solar_kwh IS NOT NULL').fetchone()[0]==0
        try:
            db.execute('UPDATE gold.parametros SET tarifa_cop_kwh=0 WHERE FALSE')
        except psycopg.errors.InsufficientPrivilege:
            db.rollback()
            resultado['bi_solo_lectura']=True
        else:
            raise AssertionError('El usuario BI tiene permisos de escritura')
    dashboard=json.loads((Path(__file__).parent/'grafana/tablero.json').read_text(encoding='utf-8'))
    vivo=api(config,'/api/dashboards/uid/'+dashboard['uid'])
    assert vivo['meta']['provisioned']
    consultas=0
    for panel in dashboard['panels']:
        for target in panel.get('targets',[]):
            consulta=target|{'intervalMs':10000,'maxDataPoints':1000}
            consulta['rawSql']=consulta['rawSql'].replace('${inversor:csv}','1,2')
            respuesta=api(config,'/api/ds/query',{'from':str(int((time.time()-3600)*1000)),
                'to':str(int(time.time()*1000)),'queries':[consulta]})
            assert not respuesta['results']['A'].get('error'),(panel['title'],respuesta)
            consultas+=1
    resultado['consultas_grafana']=consultas
    reglas=api(config,'/api/prometheus/grafana/api/v1/rules')
    rules=[r for g in reglas['data']['groups'] for r in g['rules']]
    assert len(rules)==2 and all(r['health']=='ok' for r in rules),rules
    resultado['alertas']=[{'nombre':r['name'],'estado':r['state'],'salud':r['health']} for r in rules]
    if alertas:
        muestras=[]
        activa=False
        recuperada=False
        limite=time.monotonic()+210
        while time.monotonic()<limite:
            respuesta=api(config,'/api/prometheus/grafana/api/v1/rules')
            regla=next(r for g in respuesta['data']['groups'] for r in g['rules'] if r['name']=='DEMO: sin lecturas recientes')
            estado=regla['state']
            muestras.append({'hora':datetime.now(timezone.utc).isoformat(),'estado':estado,'salud':regla['health']})
            if estado=='firing' and not activa:
                activa=True
                print('Alerta observada activa',flush=True)
            if activa and estado=='inactive':
                recuperada=True
                print('Alerta observada recuperada',flush=True)
                break
            time.sleep(5)
        resultado['demostracion_alerta']={'activa':activa,'recuperada':recuperada,'muestras':muestras}
        assert activa and recuperada,'No se observó un ciclo completo de alerta'
    destino=Path(config['OUTPUT_DIR'])/'verificacion.json'
    destino.write_text(json.dumps(resultado,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    print(json.dumps(resultado,ensure_ascii=False,default=str),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--alertas',action='store_true')
    verificar(parser.parse_args().alertas)
