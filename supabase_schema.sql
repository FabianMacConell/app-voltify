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
