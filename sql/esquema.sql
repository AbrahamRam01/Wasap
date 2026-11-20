-- =========================================
-- Esquema de la base de datos del chat (SQL Server)
-- Referencia: la base ya existe en el servidor; server.py NO ejecuta este archivo.
-- =========================================

-- =========================================
-- 1. USUARIOS
-- =========================================
CREATE TABLE Usuario (
    idUsuario INT IDENTITY(1,1) PRIMARY KEY,
    idImagen INT NOT NULL DEFAULT 1,
    nombreCompleto VARCHAR(50) NOT NULL UNIQUE,
    fechaConexion DATETIME DEFAULT GETDATE(),
    estadoUsuario BIT NOT NULL DEFAULT 1
);
GO
-- =========================================
-- 2. TIPOS DE CHAT
-- =========================================
CREATE TABLE TipoChat (
    idTipoChat INT IDENTITY(1,1) PRIMARY KEY,
    tipoChat VARCHAR(20) NOT NULL UNIQUE
);
GO

-- =========================================
-- 3. CHATS
-- =========================================
CREATE TABLE Chat (
    idChat INT IDENTITY(1,1) PRIMARY KEY,

    nombreChat VARCHAR(100),
    idTipoChat INT NOT NULL,

    fechaCreacion DATETIME DEFAULT GETDATE(),
    estadoChat BIT NOT NULL DEFAULT 1,

    CONSTRAINT FK_Chat_TipoChat
        FOREIGN KEY (idTipoChat)
        REFERENCES TipoChat(idTipoChat)
);
GO

-- =========================================
-- 4. RELACION USUARIO - CHAT
-- =========================================
CREATE TABLE Relacion_Usuario_Chat (
    idRel INT IDENTITY(1,1) PRIMARY KEY,

    idUsuario INT NOT NULL,
    idChat INT NOT NULL,

    fechaUnion DATETIME DEFAULT GETDATE(),
    estadoRel BIT NOT NULL DEFAULT 1,

    CONSTRAINT FK_Relacion_Usuario
        FOREIGN KEY (idUsuario)
        REFERENCES Usuario(idUsuario),

    CONSTRAINT FK_Relacion_Chat
        FOREIGN KEY (idChat)
        REFERENCES Chat(idChat),

    CONSTRAINT UQ_Usuario_Chat
        UNIQUE (idUsuario, idChat)
);
GO

-- =========================================
-- 5. TIPOS DE MENSAJE
-- =========================================
CREATE TABLE TipoMensaje (
    idTipoMensaje INT IDENTITY(1,1) PRIMARY KEY,
    tipoMensaje VARCHAR(20) NOT NULL UNIQUE
);
GO

-- =========================================
-- 6. MENSAJES
-- =========================================
CREATE TABLE Mensaje (
    idMensaje INT IDENTITY(1,1) PRIMARY KEY,

    idChat INT NOT NULL,
    idUsuario INT NOT NULL,
    idTipoMensaje INT NOT NULL,

    mensajeTexto VARCHAR(MAX) NOT NULL,

    fechaMensaje DATETIME DEFAULT GETDATE(),
    estadoMensaje BIT NOT NULL DEFAULT 1,

    CONSTRAINT FK_Mensaje_Chat
        FOREIGN KEY (idChat)
        REFERENCES Chat(idChat),

    CONSTRAINT FK_Mensaje_Usuario
        FOREIGN KEY (idUsuario)
        REFERENCES Usuario(idUsuario),

    CONSTRAINT FK_Mensaje_Tipo
        FOREIGN KEY (idTipoMensaje)
        REFERENCES TipoMensaje(idTipoMensaje)
);
GO


-- Tipos de chat
INSERT INTO TipoChat (tipoChat)
VALUES
    ('Privado'),
    ('Grupal');
GO

-- Tipos de mensaje
INSERT INTO TipoMensaje (tipoMensaje)
VALUES
    ('Texto'),
    ('GIF'),
    ('Imagen');
GO

ALTER TABLE Mensaje
ADD CONSTRAINT FK_Mensaje_Participante
FOREIGN KEY (idUsuario, idChat)
REFERENCES Relacion_Usuario_Chat (idUsuario, idChat);
GO

-- =========================================
-- Catálogos extra que usa el chat (no cambian la estructura):
--   'Global' -> el chat global donde entran todos
--   'Canal'  -> canales estilo WhatsApp (solo el creador publica)
-- server.py los agrega al arrancar si faltan (no hace falta correr esto).
-- =========================================
INSERT INTO TipoChat (tipoChat) VALUES ('Global'), ('Canal');
GO
