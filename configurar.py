import argparse
import secrets
from pathlib import Path

from helpers.configuracion import entorno


def preparar_configuracion():
    raiz=Path(__file__).resolve().parent
    ruta=raiz/'.env'
    if not ruta.exists():
        contenido=(raiz/'.env.example').read_text(encoding='utf-8')
        for clave in ('POSTGRES_PASSWORD','BI_PASSWORD','SIM_PASSWORD','GRAFANA_PASSWORD'):
            contenido=contenido.replace(clave+'=\n',clave+'='+secrets.token_urlsafe(24)+'\n')
        ruta.write_text(contenido,encoding='utf-8')
    config=entorno()
    for nombre in ('bronze','persistencia/compose-postgres','persistencia/compose-grafana',
                   'persistencia/k8s-postgres','persistencia/k8s-grafana','herramientas'):
        (Path(config['DATA_DIR'])/nombre).mkdir(parents=True,exist_ok=True)
    Path(config['OUTPUT_DIR']).mkdir(parents=True,exist_ok=True)


def dsn():
    import winreg
    config=entorno()
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,r'SOFTWARE\ODBC\ODBCINST.INI\PostgreSQL Unicode(x64)') as clave:
            driver=winreg.QueryValueEx(clave,'Driver')[0]
    except FileNotFoundError:
        driver=config.get('ODBC_DRIVER_PATH',str(Path(config['DATA_DIR'])/'herramientas/odbc/podbc35w.dll'))
        if not Path(driver).is_file():
            raise SystemExit('Instale PostgreSQL ODBC Unicode x64 o configure ODBC_DRIVER_PATH en .env.')
    valores={'Driver':driver,'Servername':'127.0.0.1','Port':config.get('DB_PORT','55441'),
             'Database':'solarbi','Username':'solarbi_bi','Password':config['BI_PASSWORD'],
             'SSLmode':'disable','ReadOnly':'1'}
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER,r'Software\ODBC\ODBC.INI\SolarBI') as clave:
        for nombre,valor in valores.items():
            winreg.SetValueEx(clave,nombre,0,winreg.REG_SZ,str(valor))
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER,r'Software\ODBC\ODBC.INI\ODBC Data Sources') as clave:
        winreg.SetValueEx(clave,'SolarBI',0,winreg.REG_SZ,'PostgreSQL Unicode(x64)')
    print('DSN SolarBI configurado para el usuario de solo lectura. Credenciales fuera del proyecto Power BI.')


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--dsn',action='store_true')
    args=parser.parse_args()
    preparar_configuracion()
    if args.dsn:
        dsn()
