SELECT e.inversor,i.nombre,sum(e.solar_kwh) AS solar_kwh,
       sum(e.solar_kwh)/max(i.kwp) AS rendimiento_kwh_kwp,
       sum(e.registro_s)/(count(*)*300.0) AS disponibilidad,
       sum(e.lecturas_validas)::NUMERIC/nullif(sum(e.lecturas),0) AS porcentaje_validas
FROM gold.fact_energia e JOIN gold.dim_inversor i USING(inversor)
GROUP BY e.inversor,i.nombre ORDER BY e.inversor;

WITH mensual AS (
    SELECT inversor,periodo,sum(solar_kwh) AS solar_kwh
    FROM gold.energia GROUP BY inversor,periodo
)
SELECT *,lag(solar_kwh) OVER(PARTITION BY inversor ORDER BY periodo) AS periodo_observado_anterior,
       dense_rank() OVER(PARTITION BY periodo ORDER BY solar_kwh DESC) AS posicion
FROM mensual ORDER BY periodo,inversor;

SELECT valor->>'source' AS fuente,coalesce(valor->>'context_type','Sin clasificar') AS tipo,count(*)
FROM silver.contexto GROUP BY 1,2 ORDER BY count(*) DESC;

SELECT inversor,sum(solar_kwh) AS solar_dc,sum(red_importada_kwh) AS red_ac,
       sum(bateria_descarga_kwh) AS descarga_dc,sum(bateria_carga_kwh) AS carga_bateria_dc,
       sum(carga_kwh) AS carga_ac,sum(residual_kwh) AS residual_dc_ac,
       sum(balance_s)/nullif(sum(registro_s),0) AS cobertura_balance
FROM gold.fact_energia GROUP BY inversor;

SELECT periodo,inversor,sum(costo_importado_cop) AS costo_importado_cop
FROM gold.energia GROUP BY periodo,inversor ORDER BY periodo,inversor;
