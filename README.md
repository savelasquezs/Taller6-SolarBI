# SolarBI · Taller 6

Generación solar observada y rendimiento específico por inversor. Proyecto individual de Santiago Velásquez Serna.

SQLite OpenCEM (Bronze, solo lectura) → ETL Python → PostgreSQL Silver/Gold → Power BI y Grafana. Los servicios se desarrollan con Compose y se entregan sobre kind de un nodo. Power BI y DBeaver corren en Windows.

## Requisitos y arranque

Windows, Python 3.14, Docker Desktop con contenedores Linux, kubectl 1.34 y PostgreSQL ODBC Unicode x64 para Power BI. Reservar 4 GB de RAM libre, al menos 3 GB libres en la unidad donde Docker almacena su disco y 15 GB en la unidad de datos. kind 0.30.0 se descarga y verifica automáticamente. No se necesitan cuenta cloud, Helm ni Ingress.

Desde PowerShell, en esta carpeta:

```powershell
python -m pip install -r requirements.txt
.\gestionar.ps1 up
```

El comando crea `.env` con contraseñas aleatorias si no existe, verifica y descarga únicamente los archivos necesarios de OpenCEM, inventaría SQLite, construye la imagen, crea el clúster, aplica los manifiestos, ejecuta el Job ETL y prepara Grafana y el simulador. Las descargas verificadas y una carga ya completada se reutilizan. La primera carga es más lenta que los siguientes arranques.

Configurar `DATA_DIR` y `OUTPUT_DIR` en `.env` para elegir las carpetas externas. `DOCKER_STORAGE_DRIVE` indica la unidad real del disco de Docker para comprobar el espacio; no mueve Docker. Los valores por defecto de los datos y la entrega están en D:. El script no borra datos ni cambia otros proyectos.

```powershell
.\gestionar.ps1 compose
.\gestionar.ps1 verificar
.\gestionar.ps1 down
```

`compose` permite desarrollar sin Kubernetes. `down` retira el clúster y Compose del proyecto, conservando las carpetas de datos. Para cambiar entre ambos entornos se conservan almacenes PostgreSQL separados. No ejecutar ambos modos en los mismos puertos simultáneamente.

## Acceso

| Herramienta | Dirección | Usuario |
| --- | --- | --- |
| Grafana | http://localhost:3003 | admin; clave local `GRAFANA_PASSWORD` |
| Power BI | DSN de usuario `SolarBI` | solarbi_bi, solo lectura |
| DBeaver | localhost:55441 / solarbi | solarbi o solarbi_bi |

Abrir `powerbi/SolarBI.pbip` y actualizar. Ante credenciales ODBC, seleccionar Default or Custom sin agregar una cadena; la conexión DSN usa la credencial local de solo lectura. El PBIP/BIM/PBIR es texto revisable en Git; caché y PBIX se excluyen.

## Datos y cálculos

- Fuente fija: OpenCEM v1.0.0, DOI 10.5281/zenodo.21436223. La descarga comprueba SHA-256 de los comprimidos y del SQLite descomprimido. No se descargan imágenes del cielo.
- Grano Silver: lectura por timestamp fraccionario UTC e inversor; contexto por ID. Grano Gold: energía por cinco minutos e inversor; eventos por ID contextual o episodio de batería baja. Fecha, inversor, franja horaria y tipo de evento son dimensiones compartidas; no se unen directamente los hechos.
- Integración trapezoidal con tiempos reales, división en límites de cinco minutos y separación exacta de cruces de signo. Se excluyen huecos >120 s y campos inválidos sin convertirlos en ceros. Un intervalo sin medición no implica energía cero. Los días se presentan en Asia/Shanghai.
- Rendimiento específico: kWh solares / kWp nominales de los inversores seleccionados, sin sumar la capacidad por lectura. Referencia publicada: 26 paneles ×480 W =12,48 kWp por arreglo/subsistema; no confundir con los 8 kW del inversor. No se demuestra PR sin irradiancia en el plano de los paneles.
- Cobertura: segundos observados / segundos de calendario desde el primer al último día observado de cada inversor. Calidad: lecturas completas válidas / recibidas; las coberturas por variable se conservan por separado.
- Batería: corriente positiva de descarga, negativa de carga; potencia DC = V×I. SoC bajo: <20 %. El residual del balance mezcla puntos DC y AC, pérdidas y asincronía: no es una medición de eficiencia.
- Costo importado: kWh de red importados ×991,29 COP/kWh, referencia EPM octubre 2026, oficial/exento, nivel I, activos EPM. Es un escenario colombiano sobre una instalación china. Power BI permite variar la tarifa de −50 % a +50 %.
- El máximo diario del contador `statistics.pvgeneratenergytoday` se contrasta con la integración, sin imponer igualdad cuando existen huecos, lecturas parciales o diferencias del equipo.

Los informes de inventario, checksums, reglas de calidad, conciliación y verificaciones se guardan únicamente en `OUTPUT_DIR`. No se publica contexto personal ni datos en Git. El contexto cargado minimiza campos y oculta correos, rutas de usuarios y patrones de credenciales; Bronze permanece privado e inalterado.

## Operación y Kubernetes

Namespace `solarbi`; StatefulSet PostgreSQL y PVC; Deployment Grafana con PVC y provisioning; Job ETL; Deployment simulador; Services por nombre; ConfigMap para configuración y Secret para contraseñas. Los PV locales retienen archivos en D: a través de los mounts del nodo kind. No ofrecen alta disponibilidad ni almacenamiento distribuido.

Grafana refresca cada 5 s. El simulador emite cada 10 s, conserva timestamp original y registra hora de emisión aparte. Tras seis emisiones pausa 65 s para demostrar la alerta de ausencia >45 s. La otra alerta detecta SoC <20 % durante 30 s. Son umbrales académicos; no instrucciones operativas de seguridad. Se aprovisionan al arrancar, sin mensajes externos.

Para cambiar umbrales o intervalos, editar `.env` y los archivos de provisioning correspondientes y repetir el arranque; no se modifica la imagen para cambiar una regla. `sql/02_consultas.sql` incluye agregaciones, ventanas y consulta JSONB nativa. Power BI usa la misma Gold que las tarjetas históricas de Grafana; las series operativas leen el esquema `demo` separado.

## Verificación

```powershell
python -m pytest tests -q
python verificar.py --alertas
kubectl --context kind-solarbi -n solarbi get pods,pvc,services,jobs
```

Las pruebas cubren integración temporal, medianoche, huecos, faltantes, signos, claves y privacidad. La verificación de datos comprueba el histórico completo, permisos de lectura y consultas de Grafana; `--alertas` espera activación y recuperación reales. El material de exposición, PDF y evidencias del clúster se mantienen fuera del repositorio.

## Fuente y licencia

Bartels, T. S., Wu, R., Lu, X., Chen, Y., Lu, Y., Xia, F., Yang, H., Chen, Y., & Li, T. (2026). *OpenCEM: Multimodal photovoltaic and battery microgrid dataset with context records and sky imagery (Version 1.0.0)* [Dataset]. Zenodo. https://doi.org/10.5281/zenodo.21436223. Datos bajo CC BY 4.0; conservar atribución.

Referencias: [instalación física](https://tongxin.me/opencem/dataset.html), [tarifa EPM octubre 2026](https://www.epm.com.co/content/dam/epm/clientes-y-usuarios/energia/tarifas-energia/Tarifas%202026/10.PublicacionTarifasOctubre162026_ANT_OM.pdf), [kind](https://kind.sigs.k8s.io/docs/user/quick-start/).
