param([ValidateSet('up','down','compose','verificar','cliente')][string]$Accion='up')
$ErrorActionPreference='Stop'
Set-Location -LiteralPath $PSScriptRoot
function Ejecutar {
    param([string]$Programa,[string[]]$Argumentos)
    & $Programa @Argumentos
    if($LASTEXITCODE -ne 0) { throw "Falló $Programa (código $LASTEXITCODE)" }
}
Ejecutar python @('configurar.py')
$config=@{}
Get-Content -LiteralPath '.env' | ForEach-Object {
    if($_ -match '^([^#=]+)=(.*)$') { $config[$matches[1]]=$matches[2] }
}
$kind=Join-Path $config.DATA_DIR 'herramientas/kind.exe'
if($Accion -eq 'down') {
    if(Test-Path -LiteralPath $kind) { Ejecutar $kind @('delete','cluster','--name','solarbi') }
    Ejecutar docker @('compose','down')
    Write-Output 'Servicios retirados. Datos de D: conservados.'
    exit
}
if($Accion -eq 'cliente') { Ejecutar python @('configurar.py','--dsn'); exit }
if($Accion -eq 'verificar') { Ejecutar python @('verificar.py'); exit }
Ejecutar docker @('info','--format','{{.ServerVersion}}')
$unidad=$config['DOCKER_STORAGE_DRIVE']
if(-not $unidad) { $unidad='C' }
if((Get-PSDrive $unidad).Free -lt 3GB) { throw "Docker necesita al menos 3 GB libres en $unidad`: antes de crear el clúster. No se borrará ningún dato." }
$nodoExistente=docker ps --filter 'name=^/solarbi-control-plane$' --format '{{.Names}}'
$memoriaMinima=if($nodoExistente) { 1GB } else { 4GB }
if((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory*1KB -lt $memoriaMinima) { throw 'Falta RAM libre: se requieren 4 GB para crear el clúster o 1 GB para actualizar uno existente.' }
Ejecutar python @('preparar_datos.py')
if($Accion -eq 'compose') {
    Ejecutar docker @('compose','up','-d','--build')
    exit
}
if(-not(Test-Path -LiteralPath $kind)) {
    Invoke-WebRequest 'https://github.com/kubernetes-sigs/kind/releases/download/v0.30.0/kind-windows-amd64' -OutFile $kind
}
if((Get-FileHash -LiteralPath $kind -Algorithm SHA256).Hash.ToLower() -ne 'a75fed2b6964d877461cc145b37e997ac0f59a63bd02a750134ac25378f78ce7') { throw 'Checksum incorrecto de kind' }
$clusters=& $kind get clusters
if($clusters -notcontains 'solarbi') {
    $kindYaml=Join-Path $config.DATA_DIR 'kind.yaml'
    $dataPath=$config.DATA_DIR.Replace('\','/')
    $outputPath=$config.OUTPUT_DIR.Replace('\','/')
    @"
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
  - role: control-plane
    extraMounts:
      - hostPath: '$dataPath'
        containerPath: /datos
      - hostPath: '$outputPath'
        containerPath: /entrega
"@ | Set-Content -LiteralPath $kindYaml -Encoding utf8
    Ejecutar $kind @('create','cluster','--name','solarbi','--config',$kindYaml,'--image','kindest/node:v1.34.0@sha256:7416a61b42b1662ca6ca89f02028ac133a309a2a30ba309614e8ec94d976dc5a','--wait','180s')
}
Ejecutar docker @('update','--cpus','4','--memory','4g','--memory-swap','5g','solarbi-control-plane')
Ejecutar docker @('build','--provenance=false','--tag','solarbi-app:1.0','.')
foreach($imagen in @('postgres:17.6','grafana/grafana:13.2.3')) {
    $local=docker image ls --filter "reference=$imagen" --format '{{.ID}}'
    if(-not $local) { Ejecutar docker @('pull',$imagen) }
}
$imagenes=@('solarbi-app:1.0','postgres:17.6','grafana/grafana:13.2.3')
$ids=(docker image inspect @imagenes --format '{{.Id}}') -join '|'
$archivoImagenes=Join-Path $config.DATA_DIR 'imagenes-amd64.tar'
$marcaImagenes=Join-Path $config.DATA_DIR 'imagenes-amd64.txt'
$marcaNodo=Join-Path $config.DATA_DIR 'imagenes-nodo.txt'
$idNodo=docker inspect solarbi-control-plane --format '{{.Id}}'
if(-not(Test-Path -LiteralPath $archivoImagenes) -or -not(Test-Path -LiteralPath $marcaImagenes) -or (Get-Content -LiteralPath $marcaImagenes -Raw).Trim() -ne $ids) {
    Write-Output 'Exportando imágenes linux/amd64 para kind...'
    Ejecutar docker (@('image','save','--platform','linux/amd64','--output',$archivoImagenes)+$imagenes)
    $ids | Set-Content -LiteralPath $marcaImagenes -Encoding ascii
}
$marca="$idNodo|$ids"
if(-not(Test-Path -LiteralPath $marcaNodo) -or (Get-Content -LiteralPath $marcaNodo -Raw).Trim() -ne $marca) {
    Write-Output 'Cargando imágenes en el nodo kind...'
    Ejecutar $kind @('load','image-archive',$archivoImagenes,'--name','solarbi')
    $marca | Set-Content -LiteralPath $marcaNodo -Encoding ascii
}
Ejecutar kubectl @('--context','kind-solarbi','apply','-f','k8s/namespace.yaml')
$secretFile=Join-Path $config.DATA_DIR 'credenciales.env'
$publicFile=Join-Path $config.DATA_DIR 'configuracion.env'
$privadas=@('POSTGRES_PASSWORD','BI_PASSWORD','SIM_PASSWORD','GRAFANA_PASSWORD')
($privadas | ForEach-Object { "$_=$($config[$_])" }) | Set-Content -LiteralPath $secretFile -Encoding ascii
$publicas=@('POSTGRES_DB=solarbi','POSTGRES_USER=solarbi','PGHOST=db','PGPORT=5432','DATA_DIR=/datos','OUTPUT_DIR=/salida')
foreach($clave in @('MAX_GAP_SECONDS','SOC_THRESHOLD','SOC_ALERT_SECONDS','STALE_SECONDS','REPLAY_SECONDS','REPLAY_PAUSE_AFTER','REPLAY_PAUSE_SECONDS','TARIFF_COP_KWH','PV_KWP')) { $publicas+="$clave=$($config[$clave])" }
$publicas | Set-Content -LiteralPath $publicFile -Encoding ascii
kubectl --context kind-solarbi -n solarbi create secret generic solarbi-credenciales --from-env-file=$secretFile --dry-run=client -o yaml | kubectl --context kind-solarbi apply -f - | Out-Null
if($LASTEXITCODE -ne 0) { throw 'No se pudo preparar Secret' }
kubectl --context kind-solarbi -n solarbi create configmap solarbi-config --from-env-file=$publicFile --dry-run=client -o yaml | kubectl --context kind-solarbi apply -f - | Out-Null
if($LASTEXITCODE -ne 0) { throw 'No se pudo preparar ConfigMap de parámetros' }
$alertFile=Join-Path $config.DATA_DIR 'configuracion/alertas.yaml'
kubectl --context kind-solarbi -n solarbi create configmap solarbi-grafana --from-file=grafana/provisioning/datasources/postgres.yaml --from-file=grafana/provisioning/dashboards/solarbi.yaml "--from-file=alertas.yaml=$alertFile" --from-file=grafana/tablero.json --dry-run=client -o yaml | kubectl --context kind-solarbi apply -f - | Out-Null
if($LASTEXITCODE -ne 0) { throw 'No se pudo preparar ConfigMap de Grafana' }
Ejecutar kubectl @('--context','kind-solarbi','apply','-f','k8s/almacenamiento.yaml','-f','k8s/servicios.yaml','-f','k8s/postgres.yaml')
Ejecutar kubectl @('--context','kind-solarbi','-n','solarbi','rollout','status','statefulset/postgres','--timeout=600s')
Ejecutar kubectl @('--context','kind-solarbi','-n','solarbi','delete','job','carga-historica','--ignore-not-found=true')
Ejecutar kubectl @('--context','kind-solarbi','apply','-f','k8s/etl.yaml')
Ejecutar kubectl @('--context','kind-solarbi','-n','solarbi','wait','--for=condition=complete','job/carga-historica','--timeout=3600s')
Ejecutar kubectl @('--context','kind-solarbi','apply','-f','k8s/grafana.yaml','-f','k8s/simulador.yaml')
Ejecutar kubectl @('--context','kind-solarbi','-n','solarbi','rollout','restart','deployment/grafana','deployment/simulador')
Ejecutar kubectl @('--context','kind-solarbi','-n','solarbi','rollout','status','deployment/grafana','--timeout=900s')
Ejecutar kubectl @('--context','kind-solarbi','-n','solarbi','rollout','status','deployment/simulador','--timeout=180s')
Ejecutar docker @('compose','stop','db','grafana','simulador')
foreach($par in @(@('db',$config.DB_PORT,'5432'),@('grafana',$config.GRAFANA_PORT,'3000'))) {
    $puerto=[int]$par[1]
    if(-not(Get-NetTCPConnection -State Listen -LocalPort $puerto -ErrorAction SilentlyContinue)) {
        $log=Join-Path $config.OUTPUT_DIR ('port-forward-'+$par[0]+'.log')
        $tunel=Join-Path $PSScriptRoot 'helpers/tunel.ps1'
        Start-Process powershell -WindowStyle Hidden -ArgumentList @('-NoProfile','-File',"`"$tunel`"",'-Servicio',$par[0],'-PuertoLocal',$par[1],'-PuertoRemoto',$par[2]) -RedirectStandardOutput $log -RedirectStandardError ($log+'.err')
    }
}
Ejecutar python @('configurar.py','--dsn')
Write-Output "SolarBI listo. Grafana: http://localhost:$($config.GRAFANA_PORT) · PostgreSQL: localhost:$($config.DB_PORT)"
