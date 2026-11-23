CREATE DATABASE IF NOT EXISTS bd_analitica
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE bd_analitica;

-- Eventos recibidos de los otros servicios (orden.recibida, movimiento.registrado, envio.creado, stock.bajo).
-- Además del payload JSON se guardan algunos campos en columnas para poder agrupar con SQL.
CREATE TABLE IF NOT EXISTS EVENTO_RECIBIDO (
    id INT AUTO_INCREMENT PRIMARY KEY,
    evento_id VARCHAR(100) NOT NULL UNIQUE,
    tipo_evento VARCHAR(80) NOT NULL,
    origen VARCHAR(40) NULL,
    producto_id INT NULL,
    bodega_id INT NULL,
    bodega_origen_id INT NULL,
    bodega_destino_id INT NULL,
    cliente_id INT NULL,
    cantidad INT NULL,
    tipo_movimiento VARCHAR(40) NULL,
    payload JSON NOT NULL,
    recibido_en DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_evento_tipo_fecha (tipo_evento, recibido_en)
) ENGINE=InnoDB;

-- Indicadores calculados a partir de los eventos: un valor por día (periodo) y por dimensión.
-- dimension = 'general' es el total; 'bodega', 'producto' o 'cliente' llevan su id en clave_dimension.
CREATE TABLE IF NOT EXISTS INDICADOR (
    id INT AUTO_INCREMENT PRIMARY KEY,
    nombre VARCHAR(80) NOT NULL,
    dimension VARCHAR(20) NOT NULL DEFAULT 'general',
    clave_dimension VARCHAR(40) NOT NULL DEFAULT '',
    valor DECIMAL(14, 2) NOT NULL DEFAULT 0.00,
    periodo_inicio DATE NOT NULL,
    periodo_fin DATE NOT NULL,
    calculado_en DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT uk_indicador UNIQUE (nombre, dimension, clave_dimension, periodo_inicio)
) ENGINE=InnoDB;
