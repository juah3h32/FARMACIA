-- ═══════════════════════════════════════════════════════════════════════════
-- TPN - Todo Pal Negocio - Schema de Base de Datos
-- Ejecutar en phpMyAdmin de Hostinger
-- ═══════════════════════════════════════════════════════════════════════════

SET NAMES utf8mb4;
SET time_zone = '-06:00'; -- Zona horaria México Centro

-- ─── USUARIOS ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS `users` (
  `id`             INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  `name`           VARCHAR(120)  NOT NULL,
  `email`          VARCHAR(180)  NOT NULL UNIQUE,
  `password_hash`  VARCHAR(255)  NULL,          -- NULL si sólo usa Google
  `google_id`      VARCHAR(100)  NULL UNIQUE,
  `photo_url`      VARCHAR(500)  NULL,
  `email_verified` TINYINT(1)    NOT NULL DEFAULT 0,
  `active`         TINYINT(1)    NOT NULL DEFAULT 1,
  `created_at`     DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`     DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ─── TOKENS DE SESIÓN ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS `sessions` (
  `id`         INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  `user_id`    INT UNSIGNED NOT NULL,
  `token`      VARCHAR(80)  NOT NULL UNIQUE,
  `expires_at` DATETIME     NOT NULL,
  `created_at` DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (`user_id`) REFERENCES `users`(`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ─── RESET DE CONTRASEÑA ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS `password_resets` (
  `id`         INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  `user_id`    INT UNSIGNED NOT NULL,
  `token`      VARCHAR(80)  NOT NULL UNIQUE,
  `expires_at` DATETIME     NOT NULL,
  `used`       TINYINT(1)   NOT NULL DEFAULT 0,
  `created_at` DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (`user_id`) REFERENCES `users`(`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ─── PRODUCTOS ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS `products` (
  `id`          INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  `sku`         VARCHAR(60)   NULL UNIQUE,            -- Código interno / SKU
  `name`        VARCHAR(120) NOT NULL,
  `category`    VARCHAR(60)  NOT NULL,
  `price`       DECIMAL(10,2) NOT NULL,
  `unit`        VARCHAR(20)  NOT NULL DEFAULT 'KG',   -- KG, PZA, L, etc.
  `image_url`   VARCHAR(500) NOT NULL,
  `extra_images` TEXT        NULL,  -- JSON: ["url1","url2",...] imágenes adicionales
  `promo`       VARCHAR(20)  NULL,                   -- Ej: "-10%" o NULL
  `description` TEXT         NULL,
  `stock`       INT          NOT NULL DEFAULT 0,
  `active`      TINYINT(1)   NOT NULL DEFAULT 1,
  `created_at`  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ─── PROMOCIONES / BANNERS ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS `promos` (
  `id`          INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  `title`       VARCHAR(120) NOT NULL,
  `image_url`   VARCHAR(500) NOT NULL,
  `link_url`    VARCHAR(500) NULL,
  `position`    ENUM('home_mobile','home_desktop','both') NOT NULL DEFAULT 'both',
  `sort_order`  INT          NOT NULL DEFAULT 0,
  `active`      TINYINT(1)   NOT NULL DEFAULT 1,
  `created_at`  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ─── CATEGORÍAS ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS `categories` (
  `id`          INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  `name`        VARCHAR(60)  NOT NULL UNIQUE COMMENT 'Nombre en BD, mayúsculas. Ej: VEGETALES',
  `label`       VARCHAR(80)  NOT NULL COMMENT 'Nombre para mostrar en la app. Ej: Vegetales',
  `icon`        VARCHAR(60)  NOT NULL DEFAULT 'grid-outline' COMMENT 'Nombre de ícono Ionicons',
  `img_url`     VARCHAR(500) NULL     COMMENT 'Imagen para la sección de categorías en Home',
  `sort_order`  INT          NOT NULL DEFAULT 0,
  `active`      TINYINT(1)   NOT NULL DEFAULT 1,
  `created_at`  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Categorías iniciales (ajusta a las que tengas en productos)
INSERT IGNORE INTO `categories` (name, label, icon, sort_order) VALUES
  ('VEGETALES', 'Vegetales',  'leaf-outline',        1),
  ('FRUTAS',    'Frutas',     'leaf-outline',        2),
  ('LÁCTEOS',   'Lácteos',    'nutrition-outline',   3),
  ('ACEITES',   'Aceites',    'flask-outline',       4),
  ('CEREALES',  'Cereales',   'restaurant-outline',  5),
  ('BEBIDAS',   'Bebidas',    'wine-outline',        6),
  ('LIMPIEZA',  'Limpieza',   'sparkles-outline',    7),
  ('CARNES',    'Carnes',     'fish-outline',        8),
  ('OTROS',     'Otros',      'pricetag-outline',    9);

-- ─── SUCURSALES ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS `stores` (
  `id`          INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  `name`        VARCHAR(120) NOT NULL,
  `city`        VARCHAR(80)  NOT NULL,
  `address`     VARCHAR(300) NOT NULL,
  `lat`         DECIMAL(10,7) NOT NULL,
  `lng`         DECIMAL(10,7) NOT NULL,
  `phone`       VARCHAR(20)  NULL,
  `sort_order`  INT          NOT NULL DEFAULT 0,
  `active`      TINYINT(1)   NOT NULL DEFAULT 1,
  `created_at`  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT IGNORE INTO `stores` (name, city, address, lat, lng, sort_order) VALUES
  ('20 de Noviembre', 'Morelia',    'Calle 20 de Noviembre #825, Centro Histórico', 19.7043800, -101.1836400, 1),
  ('Calle Zamora',    'Morelia',    'Calle Zamora #395, Colonia Juárez',            19.6953836, -101.1992192, 2),
  ('TPN Zacapu',      'Zacapu',     'Calle Lic. Eduardo Ruiz #178, Centro',         19.8188000, -101.7907500, 3),
  ('TPN Uruapan',     'Uruapan',    'Calle Sarabia #30, Col. Ramón Farías',         19.4185000, -102.0525000, 4),
  ('TPN Maravatío',   'Maravatío',  'Calle Álvaro Obregón #206, Centro',            19.8784000, -100.4558000, 5);

-- Corregir coordenadas en bases de datos existentes
UPDATE `stores` SET lat = 19.7043800, lng = -101.1836400, address = 'Calle 20 de Noviembre #825, Centro Histórico' WHERE name = '20 de Noviembre';
UPDATE `stores` SET lat = 19.6953836, lng = -101.1992192, address = 'Calle Zamora #395, Colonia Juárez'            WHERE name = 'Calle Zamora';
UPDATE `stores` SET lat = 19.8188000, lng = -101.7907500, address = 'Calle Lic. Eduardo Ruiz #178, Centro'         WHERE name = 'TPN Zacapu';
UPDATE `stores` SET lat = 19.4185000, lng = -102.0525000, address = 'Calle Sarabia #30, Col. Ramón Farías'         WHERE name = 'TPN Uruapan';
UPDATE `stores` SET lat = 19.8784000, lng = -100.4558000, address = 'Calle Álvaro Obregón #206, Centro'            WHERE name = 'TPN Maravatío';

-- ─── PEDIDOS ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS `orders` (
  `id`                INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  `user_id`           INT UNSIGNED NOT NULL,
  `delivery_user_id`  INT UNSIGNED NULL,
  `total`             DECIMAL(10,2) NOT NULL,
  `shipping`          DECIMAL(10,2) NOT NULL DEFAULT 0,
  `status`            ENUM('pending','accepted','preparing','picked_up','on_the_way','delivered','cancelled')
                      NOT NULL DEFAULT 'pending',
  `address`           VARCHAR(300) NULL,
  `dest_lat`          DECIMAL(10,7) NULL,
  `dest_lng`          DECIMAL(10,7) NULL,
  `delivery_lat`      DECIMAL(10,7) NULL,
  `delivery_lng`      DECIMAL(10,7) NULL,
  `store_id`          INT UNSIGNED NULL,
  `notes`             TEXT NULL,
  `payment_method`    VARCHAR(60) NULL,
  `payment_status`    VARCHAR(20) NOT NULL DEFAULT 'pending',
  `customer_name`     VARCHAR(120) NULL,
  `customer_email`    VARCHAR(180) NULL,
  `notified_nearby`   TINYINT(1) NOT NULL DEFAULT 0,
  `created_at`        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  FOREIGN KEY (`user_id`) REFERENCES `users`(`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `order_items` (
  `id`          INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  `order_id`    INT UNSIGNED NOT NULL,
  `product_id`  INT UNSIGNED NOT NULL,
  `product_name` VARCHAR(120) NOT NULL,
  `price`       DECIMAL(10,2) NOT NULL,
  `qty`         INT UNSIGNED NOT NULL DEFAULT 1,
  FOREIGN KEY (`order_id`) REFERENCES `orders`(`id`) ON DELETE CASCADE,
  FOREIGN KEY (`product_id`) REFERENCES `products`(`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ─── DATOS INICIALES DE PRODUCTOS ────────────────────────────────────────────
INSERT INTO `products` (`name`, `category`, `price`, `unit`, `image_url`, `promo`) VALUES
('JITOMATE',      'VEGETALES', 7.90,  'KG',  'https://www.todopalnegocio.com.mx/cdn/shop/products/jitomate.png', '-10%'),
('CEBOLLA',       'VEGETALES', 5.50,  'KG',  'https://www.todopalnegocio.com.mx/cdn/shop/products/jitomate.png', '-15%'),
('ZANAHORIA',     'VEGETALES', 8.20,  'KG',  'https://www.todopalnegocio.com.mx/cdn/shop/products/jitomate.png', NULL),
('PAPA',          'VEGETALES', 12.00, 'KG',  'https://www.todopalnegocio.com.mx/cdn/shop/products/jitomate.png', '-5%'),
('LIMÓN',         'VEGETALES', 15.90, 'KG',  'https://www.todopalnegocio.com.mx/cdn/shop/products/jitomate.png', NULL),
('AGUACATE',      'VEGETALES', 35.00, 'KG',  'https://www.todopalnegocio.com.mx/cdn/shop/products/jitomate.png', '-20%'),
('CHILE VERDE',   'VEGETALES', 9.90,  'KG',  'https://www.todopalnegocio.com.mx/cdn/shop/products/jitomate.png', NULL),
('LECHUGA',       'VEGETALES', 10.00, 'PZA', 'https://www.todopalnegocio.com.mx/cdn/shop/products/jitomate.png', '-10%'),
('AJO',           'VEGETALES', 4.50,  'PZA', 'https://www.todopalnegocio.com.mx/cdn/shop/products/jitomate.png', NULL),
('CILANTRO',      'VEGETALES', 3.00,  'PZA', 'https://www.todopalnegocio.com.mx/cdn/shop/products/jitomate.png', NULL),
('LECHE ENTERA',  'LÁCTEOS',   22.00, 'L',   'https://www.todopalnegocio.com.mx/cdn/shop/collections/lacteos.png', NULL),
('QUESO OAXACA',  'LÁCTEOS',   89.00, 'KG',  'https://www.todopalnegocio.com.mx/cdn/shop/collections/lacteos.png', '-8%'),
('ACEITE VEGETAL','ACEITES',   45.00, 'L',   'https://www.todopalnegocio.com.mx/cdn/shop/collections/aceites.png', NULL),
('AVENA',         'CEREALES',  18.00, 'KG',  'https://www.todopalnegocio.com.mx/cdn/shop/collections/cereales.png', '-12%'),
('CAFÉ CLÁSICO',  'BEBIDAS',   55.00, 'PZA', 'https://www.todopalnegocio.com.mx/cdn/shop/products/nescafe-classic.png', NULL);

-- ─── MIGRACIÓN (si la BD ya existe, ejecuta esto manualmente en phpMyAdmin) ───
-- ► EJECUTAR ESTO EN phpMyAdmin si tu BD ya existía antes de estos cambios:
-- ALTER TABLE `orders` ADD COLUMN IF NOT EXISTS `store_id` INT UNSIGNED NULL AFTER `delivery_lng`;
-- ALTER TABLE `orders` ADD CONSTRAINT fk_order_store FOREIGN KEY (`store_id`) REFERENCES `stores`(`id`) ON DELETE SET NULL;
-- ALTER TABLE `products` ADD COLUMN IF NOT EXISTS `sku` VARCHAR(60) NULL UNIQUE AFTER `id`;
-- ALTER TABLE `products` ADD COLUMN IF NOT EXISTS `extra_images` TEXT NULL AFTER `image_url`;
-- ALTER TABLE `products` MODIFY COLUMN `stock` INT NOT NULL DEFAULT 0;

-- ► NUEVAS MIGRACIONES — repartidores por sucursal:
-- ALTER TABLE `users` ADD COLUMN IF NOT EXISTS `role` VARCHAR(20) NOT NULL DEFAULT 'customer' AFTER `active`;
-- ALTER TABLE `users` ADD COLUMN IF NOT EXISTS `store_id` INT UNSIGNED NULL AFTER `role`;
-- ALTER TABLE `users` ADD COLUMN IF NOT EXISTS `push_token` VARCHAR(255) DEFAULT NULL;
-- ALTER TABLE `users` ADD CONSTRAINT fk_user_store FOREIGN KEY (`store_id`) REFERENCES `stores`(`id`) ON DELETE SET NULL;
-- ► Para asignar un repartidor a una sucursal:
-- UPDATE users SET role='delivery', store_id=1 WHERE id=<ID_REPARTIDOR>;
-- ► Para ver los IDs de las sucursales: SELECT id, name FROM stores;

-- ► MIGRACIÓN — columnas de pedidos:
-- ALTER TABLE `orders` ADD COLUMN IF NOT EXISTS `payment_method` VARCHAR(60) NULL;
-- ALTER TABLE `orders` ADD COLUMN IF NOT EXISTS `payment_status` VARCHAR(20) NOT NULL DEFAULT 'pending';
-- ALTER TABLE `orders` ADD COLUMN IF NOT EXISTS `customer_name` VARCHAR(120) NULL;
-- ALTER TABLE `orders` ADD COLUMN IF NOT EXISTS `customer_email` VARCHAR(180) NULL;
-- ALTER TABLE `orders` ADD COLUMN IF NOT EXISTS `notified_nearby` TINYINT(1) NOT NULL DEFAULT 0;
