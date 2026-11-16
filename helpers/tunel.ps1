param([string]$Servicio,[int]$PuertoLocal,[int]$PuertoRemoto)
while($true) {
    kubectl --context kind-solarbi -n solarbi get service $Servicio -o name 2>$null | Out-Null
    if($LASTEXITCODE -ne 0) { break }
    $pods=kubectl --context kind-solarbi -n solarbi get pods -l "app=solarbi-$Servicio" -o json 2>$null | ConvertFrom-Json
    $pod=$pods.items | Where-Object { -not $_.metadata.deletionTimestamp -and ($_.status.conditions | Where-Object { $_.type -eq 'Ready' -and $_.status -eq 'True' }) } | Select-Object -First 1
    if(-not $pod) { Start-Sleep -Seconds 2; continue }
    $trabajo=Start-Job -ArgumentList $pod.metadata.name,$PuertoLocal,$PuertoRemoto -ScriptBlock {
        param($Nombre,$Local,$Remoto)
        kubectl --context kind-solarbi -n solarbi port-forward "pod/$Nombre" "${Local}:$Remoto" --address 127.0.0.1
    }
    try {
        while($trabajo.State -eq 'Running') {
            Receive-Job $trabajo
            Wait-Job $trabajo -Timeout 3 | Out-Null
            $actual=kubectl --context kind-solarbi -n solarbi get pod $pod.metadata.name -o json 2>$null
            if($LASTEXITCODE -ne 0) { break }
            $actual=$actual | ConvertFrom-Json
            if($actual.metadata.uid -ne $pod.metadata.uid -or $actual.metadata.deletionTimestamp) { break }
        }
    } finally {
        if($trabajo.State -eq 'Running') { Stop-Job $trabajo }
        Receive-Job $trabajo
        Remove-Job $trabajo
    }
    Start-Sleep -Seconds 2
}
