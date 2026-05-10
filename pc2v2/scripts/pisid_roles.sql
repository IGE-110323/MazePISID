-- =============================================
-- PISID 2025/26 — Grupo 35
-- Criação de Roles e Permissões MySQL
-- Requer MySQL 8.0+
-- =============================================

-- 1. CRIAR ROLES
CREATE ROLE IF NOT EXISTS 'admin_bd';
CREATE ROLE IF NOT EXISTS 'admin_jogo';
CREATE ROLE IF NOT EXISTS 'jogador_python';
CREATE ROLE IF NOT EXISTS 'android';


-- 2. ADMIN_BD — acesso total
GRANT ALL PRIVILEGES ON pisid.* TO 'admin_bd';


-- 3. ADMIN_JOGO (Jogador Humano / jogo.html) — Tabelas
GRANT SELECT, INSERT, UPDATE ON pisid.Simulacao            TO 'admin_jogo';
GRANT SELECT                 ON pisid.Utilizador           TO 'admin_jogo';
GRANT SELECT, INSERT, UPDATE ON pisid.Team                 TO 'admin_jogo';
GRANT SELECT                 ON pisid.MedicoesPassagens    TO 'admin_jogo';
GRANT SELECT                 ON pisid.Temperatura          TO 'admin_jogo';
GRANT SELECT                 ON pisid.Som                  TO 'admin_jogo';
GRANT SELECT                 ON pisid.Mensagens            TO 'admin_jogo';
GRANT SELECT                 ON pisid.OcupacaoLabirinto    TO 'admin_jogo';
GRANT SELECT                 ON pisid.OcupacaoLabirintoLog TO 'admin_jogo';
GRANT SELECT                 ON pisid.Maze                 TO 'admin_jogo';
GRANT SELECT                 ON pisid.Room                 TO 'admin_jogo';
GRANT SELECT                 ON pisid.Corridor             TO 'admin_jogo';
GRANT SELECT                 ON pisid.Marsami              TO 'admin_jogo';
GRANT SELECT, INSERT, UPDATE ON pisid.SimulationConfig     TO 'admin_jogo';
GRANT SELECT                 ON pisid.CorridorStatus       TO 'admin_jogo';
GRANT SELECT                 ON pisid.CorridorStatusLog    TO 'admin_jogo';

-- 3. ADMIN_JOGO — Stored Procedures
GRANT EXECUTE ON PROCEDURE pisid.SP_IniciarSimulacao  TO 'admin_jogo';
GRANT EXECUTE ON PROCEDURE pisid.SP_CriarUtilizador   TO 'admin_jogo';
GRANT EXECUTE ON PROCEDURE pisid.SP_AlterarUtilizador TO 'admin_jogo';
GRANT EXECUTE ON PROCEDURE pisid.SP_ApagarUtilizador  TO 'admin_jogo';


-- 4. JOGADOR_PYTHON (PC2_Output) — Tabelas
GRANT SELECT ON pisid.Simulacao         TO 'jogador_python';
GRANT SELECT ON pisid.Utilizador        TO 'jogador_python';
GRANT SELECT ON pisid.Team              TO 'jogador_python';
GRANT SELECT ON pisid.Temperatura       TO 'jogador_python';
GRANT SELECT ON pisid.Som               TO 'jogador_python';
GRANT SELECT ON pisid.Mensagens         TO 'jogador_python';
GRANT SELECT ON pisid.OcupacaoLabirinto TO 'jogador_python';
GRANT SELECT ON pisid.Maze              TO 'jogador_python';
GRANT SELECT ON pisid.SimulationConfig  TO 'jogador_python';

-- 4. JOGADOR_PYTHON — Stored Procedures
GRANT EXECUTE ON PROCEDURE pisid.SP_AcionarGatilho    TO 'jogador_python';
GRANT EXECUTE ON PROCEDURE pisid.SP_RegistarHeartbeat TO 'jogador_python';


-- 5. ANDROID — só leitura, sem Stored Procedures
GRANT SELECT ON pisid.Simulacao         TO 'android';
GRANT SELECT ON pisid.Utilizador        TO 'android';
GRANT SELECT ON pisid.Temperatura       TO 'android';
GRANT SELECT ON pisid.Som               TO 'android';
GRANT SELECT ON pisid.Mensagens         TO 'android';
GRANT SELECT ON pisid.OcupacaoLabirinto TO 'android';
GRANT SELECT ON pisid.SimulationConfig  TO 'android';


-- 6. CRIAR UTILIZADORES
CREATE USER IF NOT EXISTS 'fabio'@'%'     IDENTIFIED BY 'fabio1234';
GRANT 'admin_bd'       TO 'fabio'@'%';
SET DEFAULT ROLE 'admin_bd'       TO 'fabio'@'%';

CREATE USER IF NOT EXISTS 'francisco'@'%' IDENTIFIED BY 'francisco1234';
GRANT 'admin_jogo'     TO 'francisco'@'%';
SET DEFAULT ROLE 'admin_jogo'     TO 'francisco'@'%';

CREATE USER IF NOT EXISTS 'ze'@'%'        IDENTIFIED BY 'ze1234';
GRANT 'jogador_python' TO 'ze'@'%';
SET DEFAULT ROLE 'jogador_python' TO 'ze'@'%';

CREATE USER IF NOT EXISTS 'diogo'@'%'     IDENTIFIED BY 'diogo1234';
GRANT 'android'        TO 'diogo'@'%';
SET DEFAULT ROLE 'android'        TO 'diogo'@'%';

FLUSH PRIVILEGES;


-- 7. VERIFICAÇÃO
-- SHOW GRANTS FOR 'admin_jogo';
-- SHOW GRANTS FOR 'jogador_python';
-- SHOW GRANTS FOR 'android';
-- SHOW GRANTS FOR 'francisco'@'%';