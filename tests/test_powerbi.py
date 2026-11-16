import json
from pathlib import Path


def test_modelo_sin_nombres_duplicados_y_referencias_validas():
    raiz=Path(__file__).resolve().parents[1]/'powerbi'
    modelo=json.loads((raiz/'SolarBI.SemanticModel/model.bim').read_text(encoding='utf-8'))['model']
    anotaciones={a['name']:a['value'] for a in modelo['annotations']}
    assert json.loads(anotaciones['PBI_QueryOrder'])
    entidades={}
    for tabla in modelo['tables']:
        nombres=[c['name'] for c in tabla['columns']]+[m['name'] for m in tabla.get('measures',[])]
        assert len(nombres)==len({n.casefold() for n in nombres}),tabla['name']
        entidades[tabla['name']]=set(nombres)
        if tabla['partitions'][0]['source']['type']=='calculated':
            assert all(c['type']=='calculatedTableColumn' for c in tabla['columns'])
        else:
            assert {'name':'PBI_ResultType','value':'Table'} in tabla['annotations']
    def revisar(valor):
        if isinstance(valor,dict):
            for clase in ('Column','Measure'):
                if clase in valor:
                    campo=valor[clase]
                    entidad=campo.get('Expression',{}).get('SourceRef',{}).get('Entity')
                    if entidad:
                        assert campo['Property'] in entidades[entidad]
            for contenido in valor.values():
                revisar(contenido)
        elif isinstance(valor,list):
            for contenido in valor:
                revisar(contenido)
    for archivo in (raiz/'SolarBI.Report/definition').rglob('*.json'):
        contenido=json.loads(archivo.read_text(encoding='utf-8'))
        assert contenido.get('$schema'),archivo
        revisar(contenido)
