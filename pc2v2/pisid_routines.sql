-- MySQL dump 10.13  Distrib 8.0.45, for Linux (x86_64)
--
-- Host: localhost    Database: pisid
-- ------------------------------------------------------
-- Server version	8.0.45

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!50503 SET NAMES utf8mb4 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;
/*!50003 SET @saved_cs_client      = @@character_set_client */ ;
/*!50003 SET @saved_cs_results     = @@character_set_results */ ;
/*!50003 SET @saved_col_connection = @@collation_connection */ ;
/*!50003 SET character_set_client  = utf8mb4 */ ;
/*!50003 SET character_set_results = utf8mb4 */ ;
/*!50003 SET collation_connection  = utf8mb4_unicode_ci */ ;
/*!50003 SET @saved_sql_mode       = @@sql_mode */ ;
/*!50003 SET sql_mode              = 'ONLY_FULL_GROUP_BY,STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION' */ ;
DELIMITER ;;
/*!50003 CREATE*/ /*!50017 DEFINER=`root`@`%`*/ /*!50003 TRIGGER `trg_after_corridor_status_insert` AFTER INSERT ON `CorridorStatus` FOR EACH ROW BEGIN
    INSERT INTO CorridorStatusLog (IDSimulacao, IDCorridor, Status)
    VALUES (NEW.IDSimulacao, NEW.IDCorridor, NEW.Status);
END */;;
DELIMITER ;
/*!50003 SET sql_mode              = @saved_sql_mode */ ;
/*!50003 SET character_set_client  = @saved_cs_client */ ;
/*!50003 SET character_set_results = @saved_cs_results */ ;
/*!50003 SET collation_connection  = @saved_col_connection */ ;
/*!50003 SET @saved_cs_client      = @@character_set_client */ ;
/*!50003 SET @saved_cs_results     = @@character_set_results */ ;
/*!50003 SET @saved_col_connection = @@collation_connection */ ;
/*!50003 SET character_set_client  = utf8mb4 */ ;
/*!50003 SET character_set_results = utf8mb4 */ ;
/*!50003 SET collation_connection  = utf8mb4_unicode_ci */ ;
/*!50003 SET @saved_sql_mode       = @@sql_mode */ ;
/*!50003 SET sql_mode              = 'ONLY_FULL_GROUP_BY,STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION' */ ;
DELIMITER ;;
/*!50003 CREATE*/ /*!50017 DEFINER=`root`@`%`*/ /*!50003 TRIGGER `trg_after_corridor_status_update` AFTER UPDATE ON `CorridorStatus` FOR EACH ROW BEGIN
    -- Só regista se o status mudou de facto
    IF OLD.Status <> NEW.Status THEN
        INSERT INTO CorridorStatusLog (IDSimulacao, IDCorridor, Status)
        VALUES (NEW.IDSimulacao, NEW.IDCorridor, NEW.Status);
    END IF;
END */;;
DELIMITER ;
/*!50003 SET sql_mode              = @saved_sql_mode */ ;
/*!50003 SET character_set_client  = @saved_cs_client */ ;
/*!50003 SET character_set_results = @saved_cs_results */ ;
/*!50003 SET collation_connection  = @saved_col_connection */ ;
/*!50003 SET @saved_cs_client      = @@character_set_client */ ;
/*!50003 SET @saved_cs_results     = @@character_set_results */ ;
/*!50003 SET @saved_col_connection = @@collation_connection */ ;
/*!50003 SET character_set_client  = utf8mb4 */ ;
/*!50003 SET character_set_results = utf8mb4 */ ;
/*!50003 SET collation_connection  = utf8mb4_unicode_ci */ ;
/*!50003 SET @saved_sql_mode       = @@sql_mode */ ;
/*!50003 SET sql_mode              = 'ONLY_FULL_GROUP_BY,STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION' */ ;
DELIMITER ;;
/*!50003 CREATE*/ /*!50017 DEFINER=`root`@`172.19.0.%`*/ /*!50003 TRIGGER `trg_after_medicao_insert` AFTER INSERT ON `MedicoesPassagens` FOR EACH ROW BEGIN
    DECLARE v_tipo VARCHAR(10);

    SELECT Tipo INTO v_tipo 
    FROM Marsami 
    WHERE IDMarsami = NEW.IDMarsami;

    IF NEW.SalaOrigem IS NOT NULL THEN
        UPDATE OcupacaoLabirinto
        SET
            NumeroMarsamisOdd  = GREATEST(0, NumeroMarsamisOdd  - IF(v_tipo = 'odd',  1, 0)),
            NumeroMarsamisEven = GREATEST(0, NumeroMarsamisEven - IF(v_tipo = 'even', 1, 0))
        WHERE IDJogo = NEW.IDSimulacao AND Sala = NEW.SalaOrigem;
    END IF;

    INSERT INTO OcupacaoLabirinto (IDJogo, Sala, NumeroMarsamisOdd, NumeroMarsamisEven)
    VALUES (
        NEW.IDSimulacao,
        NEW.SalaDestino,
        IF(v_tipo = 'odd',  1, 0),
        IF(v_tipo = 'even', 1, 0)
    )
    ON DUPLICATE KEY UPDATE
        NumeroMarsamisOdd  = NumeroMarsamisOdd  + IF(v_tipo = 'odd',  1, 0),
        NumeroMarsamisEven = NumeroMarsamisEven + IF(v_tipo = 'even', 1, 0);

    INSERT INTO OcupacaoLabirintoLog (IDJogo, Sala, NumeroMarsamisOdd, NumeroMarsamisEven)
    SELECT IDJogo, Sala, NumeroMarsamisOdd, NumeroMarsamisEven
    FROM OcupacaoLabirinto
    WHERE IDJogo = NEW.IDSimulacao AND Sala = NEW.SalaDestino;

    INSERT INTO Mensagens (IDSimulacao, Sala, Sensor, TipoAlerta, Msg, Hora)
    SELECT
        NEW.IDSimulacao,
        Sala,
        'MOV',
        'ODD_EQUAL_EVEN',
        CONCAT('Sala ', Sala, ': ', NumeroMarsamisOdd, ' odd = ', NumeroMarsamisEven, ' even'),
        NOW()
    FROM OcupacaoLabirinto
    WHERE IDJogo = NEW.IDSimulacao
      AND Sala = NEW.SalaDestino
      AND NumeroMarsamisOdd > 0
      AND NumeroMarsamisOdd = NumeroMarsamisEven;

END */;;
DELIMITER ;
/*!50003 SET sql_mode              = @saved_sql_mode */ ;
/*!50003 SET character_set_client  = @saved_cs_client */ ;
/*!50003 SET character_set_results = @saved_cs_results */ ;
/*!50003 SET collation_connection  = @saved_col_connection */ ;
/*!50003 SET @saved_cs_client      = @@character_set_client */ ;
/*!50003 SET @saved_cs_results     = @@character_set_results */ ;
/*!50003 SET @saved_col_connection = @@collation_connection */ ;
/*!50003 SET character_set_client  = utf8mb4 */ ;
/*!50003 SET character_set_results = utf8mb4 */ ;
/*!50003 SET collation_connection  = utf8mb4_unicode_ci */ ;
/*!50003 SET @saved_sql_mode       = @@sql_mode */ ;
/*!50003 SET sql_mode              = 'ONLY_FULL_GROUP_BY,STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION' */ ;
DELIMITER ;;
/*!50003 CREATE*/ /*!50017 DEFINER=`root`@`172.19.0.%`*/ /*!50003 TRIGGER `trg_after_som_insert` AFTER INSERT ON `Som` FOR EACH ROW BEGIN
    DECLARE v_normal_noise    DECIMAL(5,2);
    DECLARE v_noise_tol       DECIMAL(5,2);
    DECLARE v_param_ac_limit  INT;
    DECLARE v_count_above     INT;
    DECLARE v_rows            INT;

    SELECT 
        m.NormalNoise,
        m.NoiseVarToleration,
        COALESCE(s.ParamAcLimit, sc.ParamAcLimit)
    INTO v_normal_noise, v_noise_tol, v_param_ac_limit
    FROM Simulacao s
    JOIN SimulationConfig sc ON sc.IDConfig = s.IDConfig
    JOIN Maze m ON m.IDMaze = sc.IDMaze
    WHERE s.IDSimulacao = NEW.IDSimulacao;

    -- Alerta RUIDO_ALTO
    IF NEW.Som > (v_normal_noise + v_noise_tol) THEN
        INSERT INTO Mensagens (IDSimulacao, Sensor, TipoAlerta, Msg, Leitura, Hora)
        VALUES (NEW.IDSimulacao, 'SOUND', 'RUIDO_ALTO',
                CONCAT('Ruído ', NEW.Som, ' acima do limite ', v_normal_noise + v_noise_tol),
                NEW.Som, NEW.Hora);

        SELECT COUNT(*) INTO v_count_above
        FROM Som
        WHERE IDSimulacao = NEW.IDSimulacao
          AND Som > (v_normal_noise + v_noise_tol);

        IF v_count_above >= v_param_ac_limit THEN
            UPDATE Simulacao
            SET Status = 3, DataHoraFim = NOW()
            WHERE IDSimulacao = NEW.IDSimulacao AND Status = 1;

            SET v_rows = ROW_COUNT();
            IF v_rows > 0 THEN
                INSERT INTO Mensagens (IDSimulacao, Sensor, TipoAlerta, Msg, Leitura, Hora)
                VALUES (NEW.IDSimulacao, 'SOUND', 'SIM_FIM',
                        CONCAT('Simulação terminada por ruído limite: ', NEW.Som),
                        NEW.Som, NOW());
            END IF;
        END IF;
    END IF;
END */;;
DELIMITER ;
/*!50003 SET sql_mode              = @saved_sql_mode */ ;
/*!50003 SET character_set_client  = @saved_cs_client */ ;
/*!50003 SET character_set_results = @saved_cs_results */ ;
/*!50003 SET collation_connection  = @saved_col_connection */ ;
/*!50003 SET @saved_cs_client      = @@character_set_client */ ;
/*!50003 SET @saved_cs_results     = @@character_set_results */ ;
/*!50003 SET @saved_col_connection = @@collation_connection */ ;
/*!50003 SET character_set_client  = utf8mb4 */ ;
/*!50003 SET character_set_results = utf8mb4 */ ;
/*!50003 SET collation_connection  = utf8mb4_unicode_ci */ ;
/*!50003 SET @saved_sql_mode       = @@sql_mode */ ;
/*!50003 SET sql_mode              = 'ONLY_FULL_GROUP_BY,STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION' */ ;
DELIMITER ;;
/*!50003 CREATE*/ /*!50017 DEFINER=`root`@`172.19.0.%`*/ /*!50003 TRIGGER `trg_after_temperatura_insert` AFTER INSERT ON `Temperatura` FOR EACH ROW BEGIN
    DECLARE v_normal_temp     INT;
    DECLARE v_high_tol        INT;
    DECLARE v_low_tol         INT;
    DECLARE v_param_ac_limit  INT;
    DECLARE v_count_above     INT;
    DECLARE v_count_below     INT;
    DECLARE v_rows            INT;

    SELECT 
        m.NormalTemperature,
        m.TempHighToleration,
        m.TempLowToleration,
        COALESCE(s.ParamAcLimit, sc.ParamAcLimit)
    INTO v_normal_temp, v_high_tol, v_low_tol, v_param_ac_limit
    FROM Simulacao s
    JOIN SimulationConfig sc ON sc.IDConfig = s.IDConfig
    JOIN Maze m ON m.IDMaze = sc.IDMaze
    WHERE s.IDSimulacao = NEW.IDSimulacao;

    -- Alerta TEMP_ALTA
    IF NEW.Temperatura > (v_normal_temp + v_high_tol) THEN
        INSERT INTO Mensagens (IDSimulacao, Sensor, TipoAlerta, Msg, Leitura, Hora)
        VALUES (NEW.IDSimulacao, 'TEMP', 'TEMP_ALTA',
                CONCAT('Temperatura ', NEW.Temperatura, ' acima do limite ', v_normal_temp + v_high_tol),
                NEW.Temperatura, NEW.Hora);

        -- Verificar limite de leituras acima
        SELECT COUNT(*) INTO v_count_above
        FROM Temperatura
        WHERE IDSimulacao = NEW.IDSimulacao
          AND Temperatura > (v_normal_temp + v_high_tol);

        IF v_count_above >= v_param_ac_limit THEN
            UPDATE Simulacao
            SET Status = 3, DataHoraFim = NOW()
            WHERE IDSimulacao = NEW.IDSimulacao AND Status = 1;

            SET v_rows = ROW_COUNT();
            IF v_rows > 0 THEN
                INSERT INTO Mensagens (IDSimulacao, Sensor, TipoAlerta, Msg, Leitura, Hora)
                VALUES (NEW.IDSimulacao, 'TEMP', 'SIM_FIM',
                        CONCAT('Simulação terminada por temperatura limite: ', NEW.Temperatura),
                        NEW.Temperatura, NOW());
            END IF;
        END IF;

    -- Alerta TEMP_BAIXA
    ELSEIF NEW.Temperatura < (v_normal_temp - v_low_tol) THEN
        INSERT INTO Mensagens (IDSimulacao, Sensor, TipoAlerta, Msg, Leitura, Hora)
        VALUES (NEW.IDSimulacao, 'TEMP', 'TEMP_BAIXA',
                CONCAT('Temperatura ', NEW.Temperatura, ' abaixo do limite ', v_normal_temp - v_low_tol),
                NEW.Temperatura, NEW.Hora);

        SELECT COUNT(*) INTO v_count_below
        FROM Temperatura
        WHERE IDSimulacao = NEW.IDSimulacao
          AND Temperatura < (v_normal_temp - v_low_tol);

        IF v_count_below >= v_param_ac_limit THEN
            UPDATE Simulacao
            SET Status = 3, DataHoraFim = NOW()
            WHERE IDSimulacao = NEW.IDSimulacao AND Status = 1;

            SET v_rows = ROW_COUNT();
            IF v_rows > 0 THEN
                INSERT INTO Mensagens (IDSimulacao, Sensor, TipoAlerta, Msg, Leitura, Hora)
                VALUES (NEW.IDSimulacao, 'TEMP', 'SIM_FIM',
                        CONCAT('Simulação terminada por temperatura limite: ', NEW.Temperatura),
                        NEW.Temperatura, NOW());
            END IF;
        END IF;
    END IF;
END */;;
DELIMITER ;
/*!50003 SET sql_mode              = @saved_sql_mode */ ;
/*!50003 SET character_set_client  = @saved_cs_client */ ;
/*!50003 SET character_set_results = @saved_cs_results */ ;
/*!50003 SET collation_connection  = @saved_col_connection */ ;

--
-- Dumping routines for database 'pisid'
--
/*!50003 DROP PROCEDURE IF EXISTS `SP_AcionarGatilho` */;
/*!50003 SET @saved_cs_client      = @@character_set_client */ ;
/*!50003 SET @saved_cs_results     = @@character_set_results */ ;
/*!50003 SET @saved_col_connection = @@collation_connection */ ;
/*!50003 SET character_set_client  = utf8mb4 */ ;
/*!50003 SET character_set_results = utf8mb4 */ ;
/*!50003 SET collation_connection  = utf8mb4_unicode_ci */ ;
/*!50003 SET @saved_sql_mode       = @@sql_mode */ ;
/*!50003 SET sql_mode              = 'ONLY_FULL_GROUP_BY,STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION' */ ;
DELIMITER ;;
CREATE DEFINER=`root`@`%` PROCEDURE `SP_AcionarGatilho`(
    IN p_IDSimulacao    INT,
    IN p_IDRoom         INT
)
BEGIN
    DECLARE v_count_odd     INT;
    DECLARE v_count_even    INT;
    DECLARE v_tentativas    INT;
    DECLARE v_resultado     TINYINT;

    -- Verifica quantas vezes o gatilho já foi acionado nesta sala
    SELECT COUNT(*) INTO v_tentativas
    FROM TriggerLog
    WHERE IDSimulacao = p_IDSimulacao
      AND IDRoom = p_IDRoom;

    IF v_tentativas >= 3 THEN
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'Limite de 3 gatilhos por sala atingido.';
    END IF;

    -- Vai buscar ocupação atual da sala
    SELECT NumeroMarsamisOdd, NumeroMarsamisEven
    INTO v_count_odd, v_count_even
    FROM OcupacaoLabirinto
    WHERE IDJogo = p_IDSimulacao AND Sala = p_IDRoom;

    -- Verifica se odd = even no momento do gatilho
    IF v_count_odd > 0 AND v_count_odd = v_count_even THEN
        SET v_resultado = 1;   -- ganha 1 ponto

        UPDATE Simulacao
        SET Score = Score + 1
        WHERE IDSimulacao = p_IDSimulacao;
    ELSE
        SET v_resultado = -1;  -- perde 0.5 pontos

        UPDATE Simulacao
        SET Score = Score - 0.5
        WHERE IDSimulacao = p_IDSimulacao;
    END IF;

    -- Regista o gatilho
    INSERT INTO TriggerLog (IDSimulacao, IDRoom, CountOdd, CountEven, Result)
    VALUES (p_IDSimulacao, p_IDRoom, v_count_odd, v_count_even, v_resultado);

    INSERT INTO SystemLog (IDSimulacao, Component, Level, Message)
    VALUES (p_IDSimulacao, 'script3', 'INFO',
        CONCAT('Gatilho sala ', p_IDRoom, ': odd=', v_count_odd, ' even=', v_count_even, ' resultado=', v_resultado));

END ;;
DELIMITER ;
/*!50003 SET sql_mode              = @saved_sql_mode */ ;
/*!50003 SET character_set_client  = @saved_cs_client */ ;
/*!50003 SET character_set_results = @saved_cs_results */ ;
/*!50003 SET collation_connection  = @saved_col_connection */ ;
/*!50003 DROP PROCEDURE IF EXISTS `SP_AlterarJogo` */;
/*!50003 SET @saved_cs_client      = @@character_set_client */ ;
/*!50003 SET @saved_cs_results     = @@character_set_results */ ;
/*!50003 SET @saved_col_connection = @@collation_connection */ ;
/*!50003 SET character_set_client  = utf8mb4 */ ;
/*!50003 SET character_set_results = utf8mb4 */ ;
/*!50003 SET collation_connection  = utf8mb4_unicode_ci */ ;
/*!50003 SET @saved_sql_mode       = @@sql_mode */ ;
/*!50003 SET sql_mode              = 'ONLY_FULL_GROUP_BY,STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION' */ ;
DELIMITER ;;
CREATE DEFINER=`root`@`172.19.0.%` PROCEDURE `SP_AlterarJogo`(
    IN p_IDSimulacao       INT,
    IN p_IDUtilizador      INT,
    IN p_Descricao         VARCHAR(255),
    IN p_ParamAcLimit      INT,
    IN p_ErrorOutlierTemp  INT,
    IN p_ErrorOutlierSound INT,
    IN p_TimeMarsamiLive   INT
)
BEGIN
    DECLARE v_Criador INT;

    SELECT IDUtilizador INTO v_Criador
    FROM Simulacao
    WHERE IDSimulacao = p_IDSimulacao
      AND Status = 0
      AND DeletedAt IS NULL;

    IF v_Criador IS NULL THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'Simulação não encontrada ou já iniciada.';
    END IF;

    IF v_Criador != p_IDUtilizador THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'Apenas o criador pode editar esta simulação.';
    END IF;

    UPDATE Simulacao
    SET Descricao         = COALESCE(p_Descricao,         Descricao),
        ParamAcLimit      = COALESCE(p_ParamAcLimit,      ParamAcLimit),
        ErrorOutlierTemp  = COALESCE(p_ErrorOutlierTemp,  ErrorOutlierTemp),
        ErrorOutlierSound = COALESCE(p_ErrorOutlierSound, ErrorOutlierSound),
        TimeMarsamiLive   = COALESCE(p_TimeMarsamiLive,   TimeMarsamiLive)
    WHERE IDSimulacao = p_IDSimulacao AND Status = 0;

END ;;
DELIMITER ;
/*!50003 SET sql_mode              = @saved_sql_mode */ ;
/*!50003 SET character_set_client  = @saved_cs_client */ ;
/*!50003 SET character_set_results = @saved_cs_results */ ;
/*!50003 SET collation_connection  = @saved_col_connection */ ;
/*!50003 DROP PROCEDURE IF EXISTS `SP_AlterarUtilizador` */;
/*!50003 SET @saved_cs_client      = @@character_set_client */ ;
/*!50003 SET @saved_cs_results     = @@character_set_results */ ;
/*!50003 SET @saved_col_connection = @@collation_connection */ ;
/*!50003 SET character_set_client  = utf8mb4 */ ;
/*!50003 SET character_set_results = utf8mb4 */ ;
/*!50003 SET collation_connection  = utf8mb4_unicode_ci */ ;
/*!50003 SET @saved_sql_mode       = @@sql_mode */ ;
/*!50003 SET sql_mode              = 'ONLY_FULL_GROUP_BY,STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION' */ ;
DELIMITER ;;
CREATE DEFINER=`root`@`%` PROCEDURE `SP_AlterarUtilizador`(
    IN p_IDUtilizador       INT,
    IN p_IDUtilizadorSessao INT,
    IN p_Nome               VARCHAR(100),
    IN p_Telemovel          VARCHAR(12),
    IN p_DataNascimento     DATE,
    IN p_PasswordHash       VARCHAR(255)
)
BEGIN
    -- Só o próprio pode alterar os seus dados
    IF p_IDUtilizador <> p_IDUtilizadorSessao THEN
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'Apenas pode alterar os seus próprios dados.';
    END IF;

    UPDATE Utilizador
    SET
        Nome            = p_Nome,
        Telemovel       = p_Telemovel,
        DataNascimento  = p_DataNascimento,
        PasswordHash    = p_PasswordHash
    WHERE IDUtilizador = p_IDUtilizador
      AND DeletedAt IS NULL;

    INSERT INTO SystemLog (IDSimulacao, Component, Level, Message)
    VALUES (NULL, 'php', 'INFO', CONCAT('Utilizador alterado: ', p_IDUtilizador));

END ;;
DELIMITER ;
/*!50003 SET sql_mode              = @saved_sql_mode */ ;
/*!50003 SET character_set_client  = @saved_cs_client */ ;
/*!50003 SET character_set_results = @saved_cs_results */ ;
/*!50003 SET collation_connection  = @saved_col_connection */ ;
/*!50003 DROP PROCEDURE IF EXISTS `SP_ApagarUtilizador` */;
/*!50003 SET @saved_cs_client      = @@character_set_client */ ;
/*!50003 SET @saved_cs_results     = @@character_set_results */ ;
/*!50003 SET @saved_col_connection = @@collation_connection */ ;
/*!50003 SET character_set_client  = utf8mb4 */ ;
/*!50003 SET character_set_results = utf8mb4 */ ;
/*!50003 SET collation_connection  = utf8mb4_unicode_ci */ ;
/*!50003 SET @saved_sql_mode       = @@sql_mode */ ;
/*!50003 SET sql_mode              = 'ONLY_FULL_GROUP_BY,STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION' */ ;
DELIMITER ;;
CREATE DEFINER=`root`@`%` PROCEDURE `SP_ApagarUtilizador`(
    IN p_IDUtilizadorAdmin  INT,
    IN p_IDUtilizador       INT
)
BEGIN
    DECLARE v_tipo_admin VARCHAR(3);

    -- Verifica se quem chama é administrador
    SELECT Tipo INTO v_tipo_admin
    FROM Utilizador
    WHERE IDUtilizador = p_IDUtilizadorAdmin
      AND DeletedAt IS NULL;

    IF v_tipo_admin <> 'ADM' THEN
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'Apenas administradores podem apagar utilizadores.';
    END IF;

    -- Não pode apagar a si próprio
    IF p_IDUtilizadorAdmin = p_IDUtilizador THEN
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'Não pode apagar o seu próprio utilizador.';
    END IF;

    UPDATE Utilizador
    SET DeletedAt = NOW()
    WHERE IDUtilizador = p_IDUtilizador;

    INSERT INTO SystemLog (IDSimulacao, Component, Level, Message)
    VALUES (NULL, 'php', 'INFO', CONCAT('Utilizador apagado: ', p_IDUtilizador));

END ;;
DELIMITER ;
/*!50003 SET sql_mode              = @saved_sql_mode */ ;
/*!50003 SET character_set_client  = @saved_cs_client */ ;
/*!50003 SET character_set_results = @saved_cs_results */ ;
/*!50003 SET collation_connection  = @saved_col_connection */ ;
/*!50003 DROP PROCEDURE IF EXISTS `SP_CriarJogo` */;
/*!50003 SET @saved_cs_client      = @@character_set_client */ ;
/*!50003 SET @saved_cs_results     = @@character_set_results */ ;
/*!50003 SET @saved_col_connection = @@collation_connection */ ;
/*!50003 SET character_set_client  = utf8mb4 */ ;
/*!50003 SET character_set_results = utf8mb4 */ ;
/*!50003 SET collation_connection  = utf8mb4_unicode_ci */ ;
/*!50003 SET @saved_sql_mode       = @@sql_mode */ ;
/*!50003 SET sql_mode              = 'ONLY_FULL_GROUP_BY,STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION' */ ;
DELIMITER ;;
CREATE DEFINER=`root`@`172.19.0.%` PROCEDURE `SP_CriarJogo`(
    IN p_IDUtilizador INT,
    IN p_IDConfig     INT,
    IN p_Descricao    VARCHAR(255)
)
BEGIN
    DECLARE v_IDTeam INT;

    SELECT IDTeam INTO v_IDTeam
    FROM Utilizador
    WHERE IDUtilizador = p_IDUtilizador
      AND DeletedAt IS NULL;

    IF v_IDTeam IS NULL THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'Utilizador não encontrado ou inactivo.';
    END IF;

    INSERT INTO Simulacao (IDTeam, IDUtilizador, IDConfig, Descricao, Status)
    VALUES (v_IDTeam, p_IDUtilizador, p_IDConfig, p_Descricao, 0);

    SELECT LAST_INSERT_ID() AS IDSimulacao;
END ;;
DELIMITER ;
/*!50003 SET sql_mode              = @saved_sql_mode */ ;
/*!50003 SET character_set_client  = @saved_cs_client */ ;
/*!50003 SET character_set_results = @saved_cs_results */ ;
/*!50003 SET collation_connection  = @saved_col_connection */ ;
/*!50003 DROP PROCEDURE IF EXISTS `SP_CriarUtilizador` */;
/*!50003 SET @saved_cs_client      = @@character_set_client */ ;
/*!50003 SET @saved_cs_results     = @@character_set_results */ ;
/*!50003 SET @saved_col_connection = @@collation_connection */ ;
/*!50003 SET character_set_client  = utf8mb4 */ ;
/*!50003 SET character_set_results = utf8mb4 */ ;
/*!50003 SET collation_connection  = utf8mb4_unicode_ci */ ;
/*!50003 SET @saved_sql_mode       = @@sql_mode */ ;
/*!50003 SET sql_mode              = 'ONLY_FULL_GROUP_BY,STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION' */ ;
DELIMITER ;;
CREATE DEFINER=`root`@`%` PROCEDURE `SP_CriarUtilizador`(
    IN p_IDUtilizadorAdmin  INT,
    IN p_IDTeam             INT,
    IN p_Nome               VARCHAR(100),
    IN p_Telemovel          VARCHAR(12),
    IN p_Email              VARCHAR(50),
    IN p_DataNascimento     DATE,
    IN p_Tipo               ENUM('ADM','USR'),
    IN p_PasswordHash       VARCHAR(255)
)
BEGIN
    DECLARE v_tipo_admin VARCHAR(3);

    -- Verifica se quem chama é administrador
    SELECT Tipo INTO v_tipo_admin
    FROM Utilizador
    WHERE IDUtilizador = p_IDUtilizadorAdmin
      AND DeletedAt IS NULL;

    IF v_tipo_admin <> 'ADM' THEN
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'Apenas administradores podem criar utilizadores.';
    END IF;

    -- Verifica se o email já existe
    IF EXISTS (SELECT 1 FROM Utilizador WHERE Email = p_Email AND DeletedAt IS NULL) THEN
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'Email já existe.';
    END IF;

    INSERT INTO Utilizador (IDTeam, Nome, Telemovel, Email, DataNascimento, Tipo, PasswordHash)
    VALUES (p_IDTeam, p_Nome, p_Telemovel, p_Email, p_DataNascimento, p_Tipo, p_PasswordHash);

    INSERT INTO SystemLog (IDSimulacao, Component, Level, Message)
    VALUES (NULL, 'php', 'INFO', CONCAT('Utilizador criado: ', p_Email));

END ;;
DELIMITER ;
/*!50003 SET sql_mode              = @saved_sql_mode */ ;
/*!50003 SET character_set_client  = @saved_cs_client */ ;
/*!50003 SET character_set_results = @saved_cs_results */ ;
/*!50003 SET collation_connection  = @saved_col_connection */ ;
/*!50003 DROP PROCEDURE IF EXISTS `SP_IniciarSimulacao` */;
/*!50003 SET @saved_cs_client      = @@character_set_client */ ;
/*!50003 SET @saved_cs_results     = @@character_set_results */ ;
/*!50003 SET @saved_col_connection = @@collation_connection */ ;
/*!50003 SET character_set_client  = utf8mb4 */ ;
/*!50003 SET character_set_results = utf8mb4 */ ;
/*!50003 SET collation_connection  = utf8mb4_unicode_ci */ ;
/*!50003 SET @saved_sql_mode       = @@sql_mode */ ;
/*!50003 SET sql_mode              = 'ONLY_FULL_GROUP_BY,STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION' */ ;
DELIMITER ;;
CREATE DEFINER=`root`@`172.19.0.%` PROCEDURE `SP_IniciarSimulacao`(
    IN p_IDSimulacao    INT,
    IN p_IDUtilizador   INT
)
BEGIN
    DECLARE v_id_criador    INT;
    DECLARE v_status        INT;
    DECLARE v_id_config     INT;
    DECLARE v_id_maze       INT;
    DECLARE v_id_team       INT;
    DECLARE v_ativa         INT;

    -- 1. Carregar dados da simulação
    SELECT IDUtilizador, Status, IDConfig, IDTeam
    INTO v_id_criador, v_status, v_id_config, v_id_team
    FROM Simulacao
    WHERE IDSimulacao = p_IDSimulacao
      AND DeletedAt IS NULL;

    -- 2. Só o criador pode iniciar
    IF v_id_criador <> p_IDUtilizador THEN
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'Apenas o criador pode iniciar esta simulacao.';
    END IF;

    -- 3. Só pode iniciar se estiver no estado criada (Status=0)
    IF v_status <> 0 THEN
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'Simulacao ja foi iniciada ou terminada.';
    END IF;

    -- 4. Verificar se já existe simulação ativa para esta equipa
    SELECT COUNT(*) INTO v_ativa
    FROM Simulacao
    WHERE IDTeam = v_id_team
      AND Status = 1
      AND DeletedAt IS NULL;

    IF v_ativa > 0 THEN
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'Ja existe uma simulacao em curso para esta equipa.';
    END IF;

    -- 5. Verificar se simulação anterior ainda tem dados por migrar
    SELECT COUNT(*) INTO v_ativa
    FROM Simulacao
    WHERE IDTeam = v_id_team
      AND Status IN (2, 3)
      AND FlushCompleto = 0
      AND DeletedAt IS NULL;

    IF v_ativa > 0 THEN
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'Aguarde — dados da simulacao anterior ainda estao a ser migrados.';
    END IF;

    -- 6. Buscar IDMaze da config
    SELECT IDMaze INTO v_id_maze
    FROM SimulationConfig
    WHERE IDConfig = v_id_config;

    -- 7. Inicializar OcupacaoLabirinto
    INSERT INTO OcupacaoLabirinto (IDJogo, Sala, NumeroMarsamisOdd, NumeroMarsamisEven)
    SELECT p_IDSimulacao, IDRoom, 0, 0
    FROM Room
    WHERE IDMaze = v_id_maze;

    -- 8. Inicializar CorridorStatus
    INSERT INTO CorridorStatus (IDSimulacao, IDCorridor, Status)
    SELECT p_IDSimulacao, IDCorridor, 1
    FROM Corridor
    WHERE IDMaze = v_id_maze;

    -- 9. Inicializar MigrationCursor
    INSERT INTO MigrationCursor (IDSimulacao, CollectionName, LastIDMongo)
    VALUES
        (p_IDSimulacao, 'movements',    NULL),
        (p_IDSimulacao, 'temperature',  NULL),
        (p_IDSimulacao, 'sound',        NULL);

    -- 10. Atualizar estado da simulação
    UPDATE Simulacao
    SET Status = 1, DataHoraInicio = NOW()
    WHERE IDSimulacao = p_IDSimulacao;

    -- 11. Inserir comando na fila para os agentes
    INSERT INTO CommandQueue (Command, IDSimulacao, Status)
    VALUES ('start', p_IDSimulacao, 0);

    -- 12. Registar no SystemLog
    INSERT INTO SystemLog (IDSimulacao, Component, Level, Message)
    VALUES (p_IDSimulacao, 'SP_IniciarSimulacao', 'INFO',
            CONCAT('Simulacao iniciada: ', p_IDSimulacao));

END ;;
DELIMITER ;
/*!50003 SET sql_mode              = @saved_sql_mode */ ;
/*!50003 SET character_set_client  = @saved_cs_client */ ;
/*!50003 SET character_set_results = @saved_cs_results */ ;
/*!50003 SET collation_connection  = @saved_col_connection */ ;
/*!50003 DROP PROCEDURE IF EXISTS `SP_Login` */;
/*!50003 SET @saved_cs_client      = @@character_set_client */ ;
/*!50003 SET @saved_cs_results     = @@character_set_results */ ;
/*!50003 SET @saved_col_connection = @@collation_connection */ ;
/*!50003 SET character_set_client  = utf8mb4 */ ;
/*!50003 SET character_set_results = utf8mb4 */ ;
/*!50003 SET collation_connection  = utf8mb4_unicode_ci */ ;
/*!50003 SET @saved_sql_mode       = @@sql_mode */ ;
/*!50003 SET sql_mode              = 'ONLY_FULL_GROUP_BY,STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION' */ ;
DELIMITER ;;
CREATE DEFINER=`root`@`172.19.0.%` PROCEDURE `SP_Login`(IN p_Email VARCHAR(50))
BEGIN
    SELECT IDUtilizador, IDTeam, Nome, Tipo
    FROM Utilizador
    WHERE Email = p_Email
      AND DeletedAt IS NULL;
END ;;
DELIMITER ;
/*!50003 SET sql_mode              = @saved_sql_mode */ ;
/*!50003 SET character_set_client  = @saved_cs_client */ ;
/*!50003 SET character_set_results = @saved_cs_results */ ;
/*!50003 SET collation_connection  = @saved_col_connection */ ;
/*!50003 DROP PROCEDURE IF EXISTS `SP_RegistarHeartbeat` */;
/*!50003 SET @saved_cs_client      = @@character_set_client */ ;
/*!50003 SET @saved_cs_results     = @@character_set_results */ ;
/*!50003 SET @saved_col_connection = @@collation_connection */ ;
/*!50003 SET character_set_client  = utf8mb4 */ ;
/*!50003 SET character_set_results = utf8mb4 */ ;
/*!50003 SET collation_connection  = utf8mb4_unicode_ci */ ;
/*!50003 SET @saved_sql_mode       = @@sql_mode */ ;
/*!50003 SET sql_mode              = 'ONLY_FULL_GROUP_BY,STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION' */ ;
DELIMITER ;;
CREATE DEFINER=`root`@`172.19.0.%` PROCEDURE `SP_RegistarHeartbeat`(
    IN p_ServiceName VARCHAR(50),
    IN p_PCLocation  VARCHAR(10)
)
BEGIN
    INSERT INTO ServiceHealth (ServiceName, LastHeartbeat, Status, PCLocation)
    VALUES (p_ServiceName, UTC_TIMESTAMP(), 'online', p_PCLocation)
    ON DUPLICATE KEY UPDATE
        LastHeartbeat = UTC_TIMESTAMP(),
        Status        = 'online',
        PCLocation    = p_PCLocation;
END ;;
DELIMITER ;
/*!50003 SET sql_mode              = @saved_sql_mode */ ;
/*!50003 SET character_set_client  = @saved_cs_client */ ;
/*!50003 SET character_set_results = @saved_cs_results */ ;
/*!50003 SET collation_connection  = @saved_col_connection */ ;
/*!50003 DROP PROCEDURE IF EXISTS `SP_ReiniciarMigracao` */;
/*!50003 SET @saved_cs_client      = @@character_set_client */ ;
/*!50003 SET @saved_cs_results     = @@character_set_results */ ;
/*!50003 SET @saved_col_connection = @@collation_connection */ ;
/*!50003 SET character_set_client  = utf8mb4 */ ;
/*!50003 SET character_set_results = utf8mb4 */ ;
/*!50003 SET collation_connection  = utf8mb4_unicode_ci */ ;
/*!50003 SET @saved_sql_mode       = @@sql_mode */ ;
/*!50003 SET sql_mode              = 'ONLY_FULL_GROUP_BY,STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION' */ ;
DELIMITER ;;
CREATE DEFINER=`root`@`%` PROCEDURE `SP_ReiniciarMigracao`(
    IN p_IDUtilizadorAdmin  INT,
    IN p_IDSimulacao        INT
)
BEGIN
    DECLARE v_tipo_admin    VARCHAR(3);
    DECLARE v_status        INT;

    -- Verifica se é administrador
    SELECT Tipo INTO v_tipo_admin
    FROM Utilizador
    WHERE IDUtilizador = p_IDUtilizadorAdmin
      AND DeletedAt IS NULL;

    IF v_tipo_admin <> 'ADM' THEN
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'Apenas administradores podem reiniciar a migração.';
    END IF;

    -- Verifica se a simulação está em curso ou em erro
    SELECT Status INTO v_status
    FROM Simulacao
    WHERE IDSimulacao = p_IDSimulacao;

    IF v_status NOT IN (1, 4) THEN
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'Só é possível reiniciar migrações de simulações em curso ou com erro.';
    END IF;

    -- Repõe o cursor — o Script 2 vai usar o IDMedicaoMongo 
    -- para evitar duplicados mesmo recomeçando do início
    UPDATE MigrationCursor
    SET LastIDMongo = NULL, LastMigratedAt = NULL
    WHERE IDSimulacao = p_IDSimulacao;

    -- Repõe estado para em curso
    UPDATE Simulacao
    SET Status = 1
    WHERE IDSimulacao = p_IDSimulacao;

    INSERT INTO SystemLog (IDSimulacao, Component, Level, Message)
    VALUES (p_IDSimulacao, 'php', 'INFO', 'Migração reiniciada pelo administrador.');

END ;;
DELIMITER ;
/*!50003 SET sql_mode              = @saved_sql_mode */ ;
/*!50003 SET character_set_client  = @saved_cs_client */ ;
/*!50003 SET character_set_results = @saved_cs_results */ ;
/*!50003 SET collation_connection  = @saved_col_connection */ ;
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;

-- Dump completed on 2026-04-23 22:21:46
