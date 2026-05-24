-- Esquema Supabase para migración desde Google Sheets (ERP Voltify)
-- Ejecutar en el SQL Editor de Supabase antes de usar la app.

CREATE TABLE IF NOT EXISTS operaciones_tareas (
    id SERIAL PRIMARY KEY,
    tarea TEXT NOT NULL DEFAULT '',
    proyecto TEXT NOT NULL DEFAULT '',
    trabajador TEXT NOT NULL DEFAULT '',
    estado TEXT NOT NULL DEFAULT '⚪ Pendiente',
    prioridad TEXT NOT NULL DEFAULT '💤 Baja',
    fecha_inicio TEXT,
    fecha_termino TEXT,
    dias_duracion DOUBLE PRECISION
);

CREATE TABLE IF NOT EXISTS bodega_inventario (
    id SERIAL PRIMARY KEY,
    codigo INTEGER,
    familia INTEGER,
    nombre_material TEXT,
    descripcion TEXT,
    cantidad INTEGER DEFAULT 0,
    unidad TEXT DEFAULT 'un',
    fecha TEXT,
    tipo_movimiento TEXT,
    persona_responsable TEXT,
    destino TEXT,
    stock_resultante INTEGER
);

CREATE INDEX IF NOT EXISTS idx_bodega_codigo ON bodega_inventario (codigo);
CREATE INDEX IF NOT EXISTS idx_bodega_tipo_mov ON bodega_inventario (tipo_movimiento);

CREATE TABLE IF NOT EXISTS bodega_movimientos (
    id SERIAL PRIMARY KEY,
    fecha TEXT,
    tipo_movimiento TEXT,
    codigo INTEGER,
    nombre_material TEXT,
    cantidad INTEGER DEFAULT 0,
    persona_responsable TEXT,
    destino TEXT,
    detalle_destino TEXT,
    stock_resultante INTEGER
);

CREATE INDEX IF NOT EXISTS idx_bodega_mov_fecha ON bodega_movimientos (fecha DESC);
CREATE INDEX IF NOT EXISTS idx_bodega_mov_codigo ON bodega_movimientos (codigo);

CREATE TABLE IF NOT EXISTS proyectos (
    id SERIAL PRIMARY KEY,
    nombre TEXT NOT NULL UNIQUE,
    empresa TEXT DEFAULT '',
    ciudad TEXT DEFAULT '',
    num_oc TEXT DEFAULT '',
    cobro INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS proyecto_equipo (
    id SERIAL PRIMARY KEY,
    proyecto TEXT NOT NULL,
    trabajador TEXT NOT NULL,
    cargo_proyecto TEXT DEFAULT '',
    horas_asignadas DOUBLE PRECISION DEFAULT 0,
    costo_hora_estimado DOUBLE PRECISION DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_proyecto_equipo_proyecto ON proyecto_equipo (proyecto);

CREATE TABLE IF NOT EXISTS proyecto_gastos (
    id SERIAL PRIMARY KEY,
    proyecto TEXT NOT NULL,
    item TEXT DEFAULT '',
    categoria TEXT DEFAULT 'Otros',
    monto INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_proyecto_gastos_proyecto ON proyecto_gastos (proyecto);

CREATE TABLE IF NOT EXISTS proyecto_presupuesto (
    id SERIAL PRIMARY KEY,
    proyecto TEXT NOT NULL,
    concepto TEXT DEFAULT '',
    cantidad DOUBLE PRECISION DEFAULT 1,
    precio_unitario INTEGER DEFAULT 0,
    monto INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_proyecto_presupuesto_proyecto ON proyecto_presupuesto (proyecto);

CREATE TABLE IF NOT EXISTS asistencia_nomina (
    id SERIAL PRIMARY KEY,
    rut TEXT NOT NULL UNIQUE,
    trabajador TEXT NOT NULL DEFAULT '',
    cargo TEXT DEFAULT '',
    sueldo_base INTEGER DEFAULT 0,
    jornada_hrs INTEGER DEFAULT 44,
    tipo_contrato TEXT DEFAULT 'Indefinido',
    gratificacion TEXT DEFAULT '',
    afp TEXT DEFAULT '',
    dias_falta DOUBLE PRECISION DEFAULT 0,
    horas_atraso INTEGER DEFAULT 0,
    horas_extras INTEGER DEFAULT 0,
    colacion INTEGER DEFAULT 0,
    movilizacion INTEGER DEFAULT 0,
    anticipo INTEGER DEFAULT 0
);
