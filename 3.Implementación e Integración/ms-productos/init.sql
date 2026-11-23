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
    precio DECIMAL(14,2) NOT NULL DEFAULT 0.00,
    activo BOOLEAN NOT NULL DEFAULT TRUE,
    creado_en DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_producto_categoria FOREIGN KEY (categoria_id) REFERENCES CATEGORIA(id),
    CONSTRAINT fk_producto_unidad FOREIGN KEY (unidad_medida_id) REFERENCES UNIDAD_MEDIDA(id)
) ENGINE=InnoDB;

-- Proveedores que suministran cada producto (N:M). proveedor_id es una referencia lógica
-- al servicio de Proveedores (otra base de datos), por eso no tiene clave foránea física.
CREATE TABLE IF NOT EXISTS PRODUCTO_PROVEEDOR (
    producto_id INT NOT NULL,
    proveedor_id INT NOT NULL,
    PRIMARY KEY (producto_id, proveedor_id),
    INDEX idx_pp_proveedor (proveedor_id),
    CONSTRAINT fk_pp_producto FOREIGN KEY (producto_id) REFERENCES PRODUCTO(id)
) ENGINE=InnoDB;

-- Datos de ejemplo
INSERT INTO UNIDAD_MEDIDA (codigo, nombre) VALUES
    ('UN', 'Unidad'),
    ('KG', 'Kilogramo'),
    ('CJ', 'Caja');

INSERT INTO CATEGORIA (nombre, padre_id, activa) VALUES
    ('Empaques', NULL, TRUE),
    ('Cajas', 1, TRUE);

INSERT INTO PRODUCTO (sku, nombre, descripcion, categoria_id, unidad_medida_id, precio, activo) VALUES
    ('CAJ-MED-001', 'Caja mediana', 'Caja de carton mediana', 2, 1, 1500.00, TRUE),
    ('CAJ-GRA-001', 'Caja grande', 'Caja de carton grande', 2, 1, 2500.00, TRUE);

-- Los proveedores 1 y 2 son los que siembra el servicio de Proveedores
INSERT INTO PRODUCTO_PROVEEDOR (producto_id, proveedor_id) VALUES
    (1, 1), (1, 2), (2, 2);
