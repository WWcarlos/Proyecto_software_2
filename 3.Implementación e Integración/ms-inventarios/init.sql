CREATE DATABASE IF NOT EXISTS bd_inventarios
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE bd_inventarios;

CREATE TABLE IF NOT EXISTS BODEGA (
    id INT AUTO_INCREMENT PRIMARY KEY,
    codigo VARCHAR(50) NOT NULL UNIQUE,
    nombre VARCHAR(150) NOT NULL,
    ubicacion VARCHAR(255) NULL,
    activa BOOLEAN NOT NULL DEFAULT TRUE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS SALDO (
    id INT AUTO_INCREMENT PRIMARY KEY,
    producto_id INT NOT NULL,
    bodega_id INT NOT NULL,
    cantidad_disponible INT NOT NULL DEFAULT 0,
    stock_minimo INT NOT NULL DEFAULT 0,
    actualizado_en DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT uk_saldo_producto_bodega UNIQUE (producto_id, bodega_id),
    CONSTRAINT fk_saldo_bodega FOREIGN KEY (bodega_id) REFERENCES BODEGA(id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS MOVIMIENTO (
    id INT AUTO_INCREMENT PRIMARY KEY,
    tipo ENUM('ENTRADA', 'SALIDA', 'AJUSTE', 'TRASLADO', 'DEVOLUCION') NOT NULL,
    producto_id INT NOT NULL,
    cantidad INT NOT NULL,
    bodega_origen_id INT NULL,
    bodega_destino_id INT NULL,
    motivo VARCHAR(255) NULL,
    referencia_tipo ENUM('ORDEN_COMPRA', 'ENVIO', 'AJUSTE_MANUAL', 'DEVOLUCION_CLIENTE', 'DEVOLUCION_PROVEEDOR') NULL,
    referencia_id INT NULL,
    usuario_id INT NOT NULL,
    fecha DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_mov_bodega_origen FOREIGN KEY (bodega_origen_id) REFERENCES BODEGA(id),
    CONSTRAINT fk_mov_bodega_destino FOREIGN KEY (bodega_destino_id) REFERENCES BODEGA(id)
) ENGINE=InnoDB;