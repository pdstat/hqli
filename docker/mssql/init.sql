-- Create application database and user for SQL Server
IF DB_ID('hqli') IS NULL
BEGIN
    CREATE DATABASE hqli;
END
GO

USE hqli;
GO

IF NOT EXISTS (SELECT * FROM sys.sql_logins WHERE name = 'hqli')
BEGIN
    CREATE LOGIN hqli WITH PASSWORD = 'hqli', CHECK_POLICY = OFF;
END
GO

CREATE USER hqli FOR LOGIN hqli;
EXEC sp_addrolemember N'db_owner', N'hqli';
GO
