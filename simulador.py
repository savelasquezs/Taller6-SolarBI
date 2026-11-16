import time
from uuid import uuid4

import psycopg

from helpers.configuracion import conexion, entorno


def reproducir():
    config=entorno()
    intervalo=float(config.get('REPLAY_SECONDS',10))
    pausa_despues=int(config.get('REPLAY_PAUSE_AFTER',6))
    pausa=float(config.get('REPLAY_PAUSE_SECONDS',65))
    sesion=str(uuid4())
    secuencia=0
    ultimos={1:-1.0,2:-1.0}
    while True:
        try:
            with psycopg.connect(conexion(config,'solarbi_sim')) as db:
                while True:
                    filas=[]
                    for inversor in (1,2):
                        fila=db.execute('''SELECT ts,inversor,solar_w,carga_w,red_w,bateria_w,soc
                            FROM silver.lecturas WHERE inversor=%s AND ts>%s AND valida
                            ORDER BY ts LIMIT 1''',(inversor,ultimos[inversor])).fetchone()
                        if fila:
                            filas.append(fila)
                            ultimos[inversor]=fila[0]
                        else:
                            ultimos[inversor]=-1.0
                    if not filas:
                        sesion=str(uuid4())
                        time.sleep(intervalo)
                        continue
                    for fila in filas:
                        db.execute('''INSERT INTO demo.lecturas(sesion,ts_original,inversor,solar_w,carga_w,red_w,bateria_w,soc)
                            VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING''',(sesion,*fila))
                    db.execute("DELETE FROM demo.lecturas WHERE emitido<now()-interval '2 hours'")
                    db.commit()
                    secuencia+=1
                    print(f'Emisión {secuencia}: {len(filas)} inversores; sesión {sesion}',flush=True)
                    if pausa_despues>0 and secuencia%pausa_despues==0:
                        print(f'Pausa demostrativa de {pausa} segundos',flush=True)
                        time.sleep(pausa)
                    else:
                        time.sleep(intervalo)
        except psycopg.Error as error:
            print('Reconectando PostgreSQL: '+type(error).__name__,flush=True)
            time.sleep(5)


if __name__=='__main__':
    reproducir()
