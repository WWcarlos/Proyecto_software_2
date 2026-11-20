CREATE DATABASE IF NOT EXISTS bd_logistica
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE bd_logistica;

CREATE TABLE IF NOT EXISTS CLIENTE (
    id INT AUTO_INCREMENT PRIMARY KEY,
    tipo_documento VARCHAR(10) NOT NULL,
    numero_documento VARCHAR(40) NOT NULL UNIQUE,
    nombre VARCHAR(200) NOT NULL,
    direccion VARCHAR(300) NULL,
    telefono VARCHAR(40) NULL,
    email VARCHAR(160) NULL
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS PAQUETE (
    id INT AUTO_INCREMENT PRIMARY KEY,
    cliente_id INT NOT NULL,
    codigo_barras VARCHAR(60) NOT NULL,
    peso_kg DECIMAL(10,2) NULL,
    descripcion VARCHAR(300) NULL,
    estado VARCHAR(20) NOT NULL DEFAULT 'RECIBIDO',
    CONSTRAINT fk_paquete_cliente FOREIGN KEY (cliente_id) REFERENCES CLIENTE(id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS ENVIO (
    id INT AUTO_INCREMENT PRIMARY KEY,
    guia_numero VARCHAR(30) NOT NULL UNIQUE,
    cliente_id INT NOT NULL,
    bodega_origen_id INT NOT NULL,
    destino VARCHAR(300) NOT NULL,
    estado_actual VARCHAR(20) NOT NULL DEFAULT 'CREADO',
    fecha_creacion DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_envio_cliente FOREIGN KEY (cliente_id) REFERENCES CLIENTE(id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS ENVIO_PAQUETE (
    envio_id INT NOT NULL,
    paquete_id INT NOT NULL,
    PRIMARY KEY (envio_id, paquete_id),
    CONSTRAINT fk_ep_envio FOREIGN KEY (envio_id) REFERENCES ENVIO(id),
    CONSTRAINT fk_ep_paquete FOREIGN KEY (paquete_id) REFERENCES PAQUETE(id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS ENVIO_INSUMO (
    id INT AUTO_INCREMENT PRIMARY KEY,
    envio_id INT NOT NULL,
    producto_id INT NOT NULL,
    cantidad INT NOT NULL,
    movimiento_salida_id INT NULL,
    CONSTRAINT fk_insumo_envio FOREIGN KEY (envio_id) REFERENCES ENVIO(id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS HISTORIAL_ESTADO (
    id INT AUTO_INCREMENT PRIMARY KEY,
    envio_id INT NOT NULL,
    estado VARCHAR(20) NOT NULL,
    observacion VARCHAR(300) NULL,
    fecha DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_historial_envio FOREIGN KEY (envio_id) REFERENCES ENVIO(id)
) ENGINE=InnoDB;

-- Datos de ejemplo
INSERT INTO CLIENTE (tipo_documento, numero_documento, nombre, direccion, telefono, email) VALUES
    ('CC', '100200300', 'Comercial Andina', 'Cra 1 # 2-3', '3000000000', 'contacto@andina.co');

INSERT INTO PAQUETE (cliente_id, codigo_barras, peso_kg, descripcion, estado) VALUES
    (1, 'PKG-0001', 1.50, 'Caja documentos', 'EN_CUSTODIA'),
    (1, 'PKG-0002', 3.00, 'Caja repuestos', 'EN_CUSTODIA');
