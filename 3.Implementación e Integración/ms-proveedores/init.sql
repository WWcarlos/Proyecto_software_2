CREATE DATABASE IF NOT EXISTS bd_proveedores
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE bd_proveedores;

CREATE TABLE IF NOT EXISTS PROVEEDOR (
    id INT AUTO_INCREMENT PRIMARY KEY,
    nit VARCHAR(30) NOT NULL UNIQUE,
    razon_social VARCHAR(200) NOT NULL,
    contacto_nombre VARCHAR(160) NULL,
    email VARCHAR(160) NULL,
    telefono VARCHAR(40) NULL,
    direccion VARCHAR(300) NULL,
    condiciones_pago VARCHAR(120) NULL,
    plazo_entrega_dias INT NULL,
    activo BOOLEAN NOT NULL DEFAULT TRUE
) ENGINE=InnoDB;

-- Datos de ejemplo
INSERT INTO PROVEEDOR (nit, razon_social, contacto_nombre, condiciones_pago, plazo_entrega_dias, activo) VALUES
    ('900123456-7', 'Empaques del Valle S.A.', 'Ana Ruiz', '30 dias', 5, TRUE),
    ('800987654-3', 'Cartones Nacionales Ltda.', NULL, 'Contado', 2, TRUE);
