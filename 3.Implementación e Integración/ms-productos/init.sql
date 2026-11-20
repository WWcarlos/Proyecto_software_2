CREATE DATABASE IF NOT EXISTS bd_productos
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE bd_productos;

CREATE TABLE IF NOT EXISTS UNIDAD_MEDIDA (
    id INT AUTO_INCREMENT PRIMARY KEY,
    codigo VARCHAR(10) NOT NULL UNIQUE,
    nombre VARCHAR(80) NOT NULL
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS CATEGORIA (
    id INT AUTO_INCREMENT PRIMARY KEY,
    nombre VARCHAR(120) NOT NULL,
    padre_id INT NULL,
    activa BOOLEAN NOT NULL DEFAULT TRUE,
    CONSTRAINT fk_categoria_padre FOREIGN KEY (padre_id) REFERENCES CATEGORIA(id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS PRODUCTO (
    id INT AUTO_INCREMENT PRIMARY KEY,
    sku VARCHAR(60) NOT NULL UNIQUE,
    nombre VARCHAR(160) NOT NULL,
    descripcion VARCHAR(400) NULL,
    categoria_id INT NOT NULL,
    unidad_medida_id INT NOT NULL,
    activo BOOLEAN NOT NULL DEFAULT TRUE,
    CONSTRAINT fk_producto_categoria FOREIGN KEY (categoria_id) REFERENCES CATEGORIA(id),
    CONSTRAINT fk_producto_unidad FOREIGN KEY (unidad_medida_id) REFERENCES UNIDAD_MEDIDA(id)
) ENGINE=InnoDB;

-- Datos de ejemplo
INSERT INTO UNIDAD_MEDIDA (codigo, nombre) VALUES
    ('UN', 'Unidad'),
    ('KG', 'Kilogramo'),
    ('CJ', 'Caja');

INSERT INTO CATEGORIA (nombre, padre_id, activa) VALUES
    ('Empaques', NULL, TRUE),
    ('Cajas', 1, TRUE);

INSERT INTO PRODUCTO (sku, nombre, descripcion, categoria_id, unidad_medida_id, activo) VALUES
    ('CAJ-MED-001', 'Caja mediana', 'Caja de carton mediana', 2, 1, TRUE),
    ('CAJ-GRA-001', 'Caja grande', 'Caja de carton grande', 2, 1, TRUE);
