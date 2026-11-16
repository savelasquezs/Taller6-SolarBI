CREATE SCHEMA IF NOT EXISTS silver;
CREATE SCHEMA IF NOT EXISTS gold;
CREATE SCHEMA IF NOT EXISTS demo;

CREATE TABLE IF NOT EXISTS silver.lecturas (
    ts DOUBLE PRECISION NOT NULL,
    inversor SMALLINT NOT NULL CHECK(inversor IN (1,2)),
    solar_w DOUBLE PRECISION CHECK(solar_w>=0),
    carga_w DOUBLE PRECISION CHECK(carga_w>=0),
    red_w DOUBLE PRECISION,
    bateria_v DOUBLE PRECISION CHECK(bateria_v>=0),
    bateria_a DOUBLE PRECISION,
    bateria_w DOUBLE PRECISION,
    soc DOUBLE PRECISION CHECK(soc BETWEEN 0 AND 100),
    valida BOOLEAN NOT NULL,
    errores TEXT[] NOT NULL,
    PRIMARY KEY(ts,inversor)
);
CREATE INDEX IF NOT EXISTS lecturas_inversor_ts ON silver.lecturas(inversor,ts);

CREATE TABLE IF NOT EXISTS silver.contexto (
    id BIGINT PRIMARY KEY,
    registrado TIMESTAMPTZ NOT NULL,
    inicio TIMESTAMPTZ NOT NULL,
    fin TIMESTAMPTZ NOT NULL CHECK(fin>=inicio),
    valor JSONB NOT NULL CHECK(jsonb_typeof(valor)='object')
);
CREATE TABLE IF NOT EXISTS silver.ejecuciones (
    huella TEXT PRIMARY KEY,
    inicio TIMESTAMPTZ NOT NULL DEFAULT now(),
    fin TIMESTAMPTZ,
    resumen JSONB NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS gold.dim_fecha (
    fecha_id INTEGER PRIMARY KEY,
    fecha DATE NOT NULL UNIQUE,
    anio SMALLINT NOT NULL,
    mes SMALLINT NOT NULL,
    periodo TEXT NOT NULL,
    dia SMALLINT NOT NULL,
    dia_semana SMALLINT NOT NULL
);
CREATE TABLE IF NOT EXISTS gold.dim_inversor (
    inversor SMALLINT PRIMARY KEY,
    nombre TEXT NOT NULL,
    carga TEXT NOT NULL,
    kwp NUMERIC(8,3),
    fuente_capacidad TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS gold.dim_franja (
    franja_id SMALLINT PRIMARY KEY,
    hora SMALLINT NOT NULL,
    minuto SMALLINT NOT NULL,
    franja TEXT NOT NULL
);
INSERT INTO gold.dim_franja
SELECT n,n/12,(n%12)*5,
       CASE WHEN n<72 THEN 'Madrugada' WHEN n<144 THEN 'Mañana'
            WHEN n<216 THEN 'Tarde' ELSE 'Noche' END
FROM generate_series(0,287) n ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS gold.dim_tipo_evento (
    tipo TEXT PRIMARY KEY,
    descripcion TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS gold.fact_energia (
    ts DOUBLE PRECISION NOT NULL,
    inversor SMALLINT NOT NULL REFERENCES gold.dim_inversor,
    fecha_id INTEGER NOT NULL REFERENCES gold.dim_fecha,
    franja_id SMALLINT NOT NULL REFERENCES gold.dim_franja,
    solar_kwh DOUBLE PRECISION,
    carga_kwh DOUBLE PRECISION,
    red_importada_kwh DOUBLE PRECISION,
    red_exportada_kwh DOUBLE PRECISION,
    bateria_descarga_kwh DOUBLE PRECISION,
    bateria_carga_kwh DOUBLE PRECISION,
    residual_kwh DOUBLE PRECISION,
    registro_s DOUBLE PRECISION NOT NULL CHECK(registro_s BETWEEN 0 AND 300.00001),
    solar_s DOUBLE PRECISION NOT NULL,
    carga_s DOUBLE PRECISION NOT NULL,
    red_s DOUBLE PRECISION NOT NULL,
    bateria_s DOUBLE PRECISION NOT NULL,
    soc_s DOUBLE PRECISION NOT NULL,
    soc_bajo_s DOUBLE PRECISION NOT NULL,
    balance_s DOUBLE PRECISION NOT NULL,
    soc_integral DOUBLE PRECISION NOT NULL,
    lecturas INTEGER NOT NULL,
    lecturas_validas INTEGER NOT NULL CHECK(lecturas_validas<=lecturas),
    PRIMARY KEY(ts,inversor)
);
CREATE INDEX IF NOT EXISTS energia_fecha_inversor ON gold.fact_energia(fecha_id,inversor);
CREATE TABLE IF NOT EXISTS gold.fact_eventos (
    evento_id TEXT PRIMARY KEY,
    inversor SMALLINT NOT NULL REFERENCES gold.dim_inversor,
    fecha_id INTEGER NOT NULL REFERENCES gold.dim_fecha,
    franja_id SMALLINT NOT NULL REFERENCES gold.dim_franja,
    tipo TEXT NOT NULL REFERENCES gold.dim_tipo_evento,
    inicio TIMESTAMPTZ NOT NULL,
    fin TIMESTAMPTZ NOT NULL CHECK(fin>=inicio),
    fuente TEXT NOT NULL,
    descripcion TEXT
);
CREATE INDEX IF NOT EXISTS eventos_fecha_inversor ON gold.fact_eventos(fecha_id,inversor);

CREATE TABLE IF NOT EXISTS gold.parametros (
    id BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK(id),
    tarifa_cop_kwh NUMERIC(12,2) NOT NULL CHECK(tarifa_cop_kwh>0),
    fuente_tarifa TEXT NOT NULL,
    max_gap_s INTEGER NOT NULL,
    soc_umbral NUMERIC NOT NULL
);

CREATE OR REPLACE VIEW gold.energia AS
SELECT e.*,to_timestamp(ts) AS instante,
       f.fecha,f.anio,f.mes,f.periodo,m.nombre AS nombre_inversor,m.kwp,
       h.franja,h.hora,
       e.solar_kwh/nullif(m.kwp,0) AS rendimiento_kwh_kwp,
       e.registro_s/300.0 AS disponibilidad,
       e.lecturas_validas::NUMERIC/nullif(e.lecturas,0) AS porcentaje_validas,
       e.soc_integral/nullif(e.soc_s,0) AS soc_promedio,
       e.soc_bajo_s/nullif(e.soc_s,0) AS tiempo_soc_bajo,
       e.red_importada_kwh*p.tarifa_cop_kwh AS costo_importado_cop
FROM gold.fact_energia e
JOIN gold.dim_fecha f USING(fecha_id)
JOIN gold.dim_inversor m USING(inversor)
JOIN gold.dim_franja h USING(franja_id)
CROSS JOIN gold.parametros p;

CREATE TABLE IF NOT EXISTS demo.lecturas (
    secuencia BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sesion TEXT NOT NULL,
    ts_original DOUBLE PRECISION NOT NULL,
    inversor SMALLINT NOT NULL CHECK(inversor IN (1,2)),
    emitido TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    solar_w DOUBLE PRECISION,
    carga_w DOUBLE PRECISION,
    red_w DOUBLE PRECISION,
    bateria_w DOUBLE PRECISION,
    soc DOUBLE PRECISION,
    UNIQUE(sesion,ts_original,inversor)
);
CREATE INDEX IF NOT EXISTS demo_emitido_inversor ON demo.lecturas(inversor,emitido DESC);
CREATE OR REPLACE VIEW demo.ultima AS
SELECT DISTINCT ON (inversor) * FROM demo.lecturas ORDER BY inversor,emitido DESC,secuencia DESC;
