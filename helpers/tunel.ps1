param([string]$Servicio,[int]$PuertoLocal,[int]$PuertoRemoto)
while($true) {
    kubectl --context kind-solarbi -n solarbi get service $Servicio -o name 2>$null | Out-Null
    if($LASTEXITCODE -ne 0) { break }
    kubectl --context kind-solarbi -n solarbi port-forward "service/$Servicio" "${PuertoLocal}:$PuertoRemoto" --address 127.0.0.1
    Start-Sleep -Seconds 2
}
