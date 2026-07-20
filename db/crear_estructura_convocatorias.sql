PRAGMA foreign_keys = ON;

BEGIN;

CREATE TABLE IF NOT EXISTS convocatorias (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo TEXT NOT NULL UNIQUE,
    cuerpo TEXT NOT NULL,
    numero INTEGER NOT NULL,
    anio INTEGER NOT NULL,
    nombre TEXT NOT NULL,
    examen_modelo TEXT,
    total_preguntas INTEGER NOT NULL CHECK (total_preguntas > 0),
    tiempo_minutos INTEGER CHECK (tiempo_minutos IS NULL OR tiempo_minutos > 0),
    valor_acierto REAL NOT NULL DEFAULT 1,
    valor_error REAL NOT NULL DEFAULT 0,
    valor_blanco REAL NOT NULL DEFAULT 0,
    nota_maxima REAL NOT NULL DEFAULT 10 CHECK (nota_maxima > 0),
    puntos_maximos REAL NOT NULL CHECK (puntos_maximos > 0),
    puntos_aprobado REAL NOT NULL CHECK (puntos_aprobado >= 0 AND puntos_aprobado <= puntos_maximos),
    estado TEXT NOT NULL DEFAULT 'BORRADOR' CHECK (estado IN ('BORRADOR', 'ACTIVA', 'CERRADA')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (cuerpo, numero, anio)
);

CREATE TABLE IF NOT EXISTS partes_convocatoria (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    convocatoria_id INTEGER NOT NULL,
    codigo TEXT NOT NULL,
    nombre TEXT NOT NULL,
    orden INTEGER NOT NULL,
    numero_preguntas INTEGER NOT NULL CHECK (numero_preguntas >= 0),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (convocatoria_id) REFERENCES convocatorias(id) ON DELETE CASCADE,
    UNIQUE (convocatoria_id, codigo),
    UNIQUE (convocatoria_id, orden)
);

CREATE TABLE IF NOT EXISTS temas_convocatoria (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    convocatoria_id INTEGER NOT NULL,
    parte_id INTEGER NOT NULL,
    numero_tema INTEGER NOT NULL CHECK (numero_tema > 0),
    bloque TEXT,
    titulo TEXT NOT NULL,
    descripcion_oficial TEXT NOT NULL,
    preguntas_modelo INTEGER CHECK (preguntas_modelo IS NULL OR preguntas_modelo >= 0),
    orden INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (convocatoria_id) REFERENCES convocatorias(id) ON DELETE CASCADE,
    FOREIGN KEY (parte_id) REFERENCES partes_convocatoria(id) ON DELETE CASCADE,
    UNIQUE (convocatoria_id, parte_id, numero_tema),
    UNIQUE (convocatoria_id, orden)
);

CREATE TABLE IF NOT EXISTS requisitos_examen (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    convocatoria_id INTEGER NOT NULL,
    tipo_requisito TEXT NOT NULL CHECK (tipo_requisito IN ('BLOQUE', 'ATRIBUTO')),
    referencia TEXT NOT NULL,
    cantidad INTEGER NOT NULL CHECK (cantidad >= 0),
    descripcion TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (convocatoria_id) REFERENCES convocatorias(id) ON DELETE CASCADE,
    UNIQUE (convocatoria_id, tipo_requisito, referencia)
);

CREATE TABLE IF NOT EXISTS documentos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo_documento TEXT NOT NULL CHECK (tipo_documento IN ('JURIDICO', 'NO_JURIDICO')),
    nombre_documento TEXT NOT NULL,
    nombre_norma TEXT,
    id_boe TEXT,
    articulo TEXT,
    titulo_articulo TEXT,
    tema_no_juridico TEXT,
    seccion TEXT,
    texto TEXT NOT NULL,
    fuente TEXT,
    ruta_fichero TEXT,
    fecha_version TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (
        (tipo_documento = 'JURIDICO' AND nombre_norma IS NOT NULL AND articulo IS NOT NULL)
        OR
        (tipo_documento = 'NO_JURIDICO' AND tema_no_juridico IS NOT NULL)
    )
);

CREATE TABLE IF NOT EXISTS corpus_convocatoria (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    convocatoria_id INTEGER NOT NULL,
    tema_id INTEGER NOT NULL,
    documento_id INTEGER NOT NULL,
    estado_validacion TEXT NOT NULL DEFAULT 'PENDIENTE' CHECK (estado_validacion IN ('PENDIENTE', 'VALIDADO', 'DESCARTADO')),
    observaciones TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (convocatoria_id) REFERENCES convocatorias(id) ON DELETE CASCADE,
    FOREIGN KEY (tema_id) REFERENCES temas_convocatoria(id) ON DELETE CASCADE,
    FOREIGN KEY (documento_id) REFERENCES documentos(id) ON DELETE CASCADE,
    UNIQUE (convocatoria_id, tema_id, documento_id)
);

CREATE TABLE IF NOT EXISTS banco_preguntas_convocatoria (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    convocatoria_id INTEGER NOT NULL,
    pregunta_general_id INTEGER NOT NULL,
    enunciado TEXT NOT NULL,
    opcion_a TEXT NOT NULL,
    opcion_b TEXT NOT NULL,
    opcion_c TEXT NOT NULL,
    opcion_d TEXT NOT NULL,
    respuesta_correcta TEXT NOT NULL CHECK (respuesta_correcta IN ('A', 'B', 'C', 'D')),
    tipo_clasificacion TEXT NOT NULL CHECK (tipo_clasificacion IN ('JURIDICA', 'INFORMATICA', 'NO_JURIDICA', 'PENDIENTE')),
    nombre_norma TEXT,
    articulo TEXT,
    tema_no_juridico TEXT,
    parte_id INTEGER NOT NULL,
    tema_id INTEGER NOT NULL,
    es_teorico_practica INTEGER NOT NULL DEFAULT 0 CHECK (es_teorico_practica IN (0, 1)),
    estado_validacion TEXT NOT NULL DEFAULT 'VALIDADA' CHECK (estado_validacion IN ('PENDIENTE', 'VALIDADA', 'DESCARTADA')),
    motivo_validacion TEXT,
    fecha_validacion TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (convocatoria_id) REFERENCES convocatorias(id) ON DELETE CASCADE,
    FOREIGN KEY (parte_id) REFERENCES partes_convocatoria(id) ON DELETE RESTRICT,
    FOREIGN KEY (tema_id) REFERENCES temas_convocatoria(id) ON DELETE RESTRICT,
    UNIQUE (convocatoria_id, pregunta_general_id)
);

CREATE INDEX IF NOT EXISTS idx_partes_convocatoria ON partes_convocatoria (convocatoria_id, orden);
CREATE INDEX IF NOT EXISTS idx_temas_convocatoria ON temas_convocatoria (convocatoria_id, parte_id, numero_tema);
CREATE INDEX IF NOT EXISTS idx_requisitos_convocatoria ON requisitos_examen (convocatoria_id);
CREATE INDEX IF NOT EXISTS idx_documentos_juridicos ON documentos (nombre_norma, articulo);
CREATE INDEX IF NOT EXISTS idx_documentos_no_juridicos ON documentos (tema_no_juridico);
CREATE INDEX IF NOT EXISTS idx_corpus_convocatoria ON corpus_convocatoria (convocatoria_id, tema_id, estado_validacion);
CREATE INDEX IF NOT EXISTS idx_banco_convocatoria_tema ON banco_preguntas_convocatoria (convocatoria_id, parte_id, tema_id);
CREATE INDEX IF NOT EXISTS idx_banco_convocatoria_practica ON banco_preguntas_convocatoria (convocatoria_id, es_teorico_practica);

COMMIT;