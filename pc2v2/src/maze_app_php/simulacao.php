<?php
error_reporting(E_ALL);
ini_set('display_errors', 1);
header('Content-Type: application/json');
header('Access-Control-Allow-Origin: *');

require_once 'db_config.php';

$response = array('success' => false, 'message' => '', 'data' => null);

$email    = $_REQUEST['email']    ?? '';
$database = $_REQUEST['database'] ?? '';
$action   = $_REQUEST['action']   ?? '';

if (empty($email) || empty($database)) {
    $response['message'] = 'Preencha todos os campos (email, database).';
    echo json_encode($response);
    exit;
}

// Usado pelo jogo.html — role admin_jogo (francisco)
$conn = new mysqli(DB_HOST, DB_USER_JOGO, DB_PASS_JOGO, $database);

if ($conn->connect_error) {
    $response['message'] = "Erro de conexão: " . $conn->connect_error;
    echo json_encode($response);
    exit;
}

$stmt = $conn->prepare("SELECT IDUtilizador, IDTeam FROM Utilizador WHERE Email = ? AND DeletedAt IS NULL");
$stmt->bind_param("s", $email);
$stmt->execute();
$user = $stmt->get_result()->fetch_assoc();
$stmt->close();

if (!$user) {
    $response['message'] = 'Utilizador não encontrado.';
    echo json_encode($response);
    exit;
}

$id_utilizador = $user['IDUtilizador'];
$id_team       = $user['IDTeam'];

// ── AÇÃO: listar simulações da equipa ─────────────────────────────────────
if ($action === 'list') {
    $sql = "SELECT s.IDSimulacao, s.Descricao, s.Status, t.PlayerNumber,
                   s.DataHoraInicio, s.DataHoraFim, s.FlushCompleto, s.Score
            FROM Simulacao s
            JOIN Team t ON t.IDTeam = s.IDTeam
            WHERE s.IDTeam = ? AND s.DeletedAt IS NULL
            ORDER BY s.IDSimulacao DESC
            LIMIT 20";
    $stmt = $conn->prepare($sql);
    $stmt->bind_param("i", $id_team);
    $stmt->execute();
    $result = $stmt->get_result();
    $sims   = array();
    while ($row = $result->fetch_assoc()) {
        $sims[] = $row;
    }
    $stmt->close();
    $response['success'] = true;
    $response['data']    = $sims;
    $response['message'] = 'Simulações carregadas.';

// ── AÇÃO: criar simulação ─────────────────────────────────────────────────
} elseif ($action === 'create') {
    $descricao = $_REQUEST['descricao'] ?? 'Nova simulação';
    $id_config = (int)($_REQUEST['id_config'] ?? 1);

    try {
        $desc_safe = $conn->real_escape_string($descricao);
        $result    = $conn->query("CALL SP_CriarJogo($id_utilizador, $id_config, '$desc_safe')");
        if ($result) {
            $row    = $result->fetch_assoc();
            $new_id = $row['IDSimulacao'];
            $response['success'] = true;
            $response['data']    = array('IDSimulacao' => $new_id);
            $response['message'] = "Simulação $new_id criada com sucesso.";
        } else {
            $response['message'] = 'Erro ao criar simulação: ' . $conn->error;
        }
    } catch (mysqli_sql_exception $e) {
        $response['message'] = $e->getMessage();
    }

// ── AÇÃO: iniciar simulação ───────────────────────────────────────────────
} elseif ($action === 'start') {
    $id_simulacao = (int)($_REQUEST['id_simulacao'] ?? 0);

    if ($id_simulacao <= 0) {
        $response['message'] = 'ID de simulação inválido.';
        echo json_encode($response);
        exit;
    }

    try {
        if ($conn->query("CALL SP_IniciarSimulacao($id_simulacao, $id_utilizador)")) {
            $response['success'] = true;
            $response['message'] = "Simulação $id_simulacao iniciada com sucesso.";
            $response['data']    = array('IDSimulacao' => $id_simulacao);
        } else {
            $response['message'] = 'Erro ao iniciar simulação: ' . $conn->error;
        }
    } catch (mysqli_sql_exception $e) {
        $response['message'] = $e->getMessage();
    }

// ── AÇÃO: editar simulação ────────────────────────────────────────────────
} elseif ($action === 'edit') {
    $id_simulacao        = (int)($_REQUEST['id_simulacao']        ?? 0);
    $descricao           = $_REQUEST['descricao']                 ?? null;
    $param_ac_limit      = isset($_REQUEST['param_ac_limit'])      ? (int)$_REQUEST['param_ac_limit']      : 'NULL';
    $error_outlier_temp  = isset($_REQUEST['error_outlier_temp'])  ? (int)$_REQUEST['error_outlier_temp']  : 'NULL';
    $error_outlier_sound = isset($_REQUEST['error_outlier_sound']) ? (int)$_REQUEST['error_outlier_sound'] : 'NULL';
    $time_marsami_live   = isset($_REQUEST['time_marsami_live'])   ? (int)$_REQUEST['time_marsami_live']   : 'NULL';
    $desc_safe           = $descricao ? "'" . $conn->real_escape_string($descricao) . "'" : 'NULL';

    try {
        $conn->query("CALL SP_AlterarJogo($id_simulacao, $id_utilizador, $desc_safe, $param_ac_limit, $error_outlier_temp, $error_outlier_sound, $time_marsami_live)");
        $response['success'] = true;
        $response['message'] = 'Simulação atualizada.';
    } catch (mysqli_sql_exception $e) {
        $response['message'] = $e->getMessage();
    }

} else {
    $response['message'] = 'Ação inválida. Use: list, create, start, edit';
}

$conn->close();
echo json_encode($response);
?>