<?php
error_reporting(E_ALL);
ini_set('display_errors', 1);
header('Content-Type: application/json');
header('Access-Control-Allow-Origin: *');

require_once 'db_config.php';

$response = array('success' => false, 'message' => '', 'data' => null);

$database = $_REQUEST['database'] ?? '';
$action   = $_REQUEST['action']   ?? '';

if (empty($database)) {
    $response['message'] = 'Database em falta.';
    echo json_encode($response);
    exit;
}

$conn = new mysqli(DB_HOST, DB_USER_JOGO, DB_PASS_JOGO, $database);
if ($conn->connect_error) {
    $response['message'] = "Erro de conexão: " . $conn->connect_error;
    echo json_encode($response);
    exit;
}

// ── Listar utilizadores ───────────────────────────────────────────────────
if ($action === 'list') {
    $result = $conn->query("
        SELECT u.IDUtilizador, u.Nome, u.Email, u.Telemovel,
               u.Tipo, u.IDTeam, t.Name as NomeEquipa
        FROM Utilizador u
        LEFT JOIN Team t ON t.IDTeam = u.IDTeam
        WHERE u.DeletedAt IS NULL
        ORDER BY u.IDUtilizador DESC
    ");
    $users = array();
    while ($row = $result->fetch_assoc()) $users[] = $row;
    $response['success'] = true;
    $response['data']    = $users;

// ── Criar utilizador ──────────────────────────────────────────────────────
} elseif ($action === 'create') {
    $nome           = $_REQUEST['nome']            ?? '';
    $email          = $_REQUEST['email']           ?? '';
    $password       = $_REQUEST['password']        ?? '';
    $tipo           = $_REQUEST['tipo']            ?? 'USR';
    $id_team        = $_REQUEST['id_team']         ?? null;
    $telemovel      = $_REQUEST['telemovel']       ?? null;
    $data_nasc      = $_REQUEST['data_nascimento'] ?? null;

    if (empty($nome) || empty($email) || empty($password)) {
        $response['message'] = 'Nome, email e password são obrigatórios.';
        echo json_encode($response);
        exit;
    }

    try {
        $id_team   = $id_team   ? (int)$id_team : null;
        $data_nasc = $data_nasc ?: null;

        $stmt = $conn->prepare("CALL SP_CriarUtilizador(?, ?, SHA2(?, 256), ?, ?, ?, ?)");
        $stmt->bind_param("sssssss",
            $nome, $email, $password, $tipo,
            $id_team, $telemovel, $data_nasc
        );
        $stmt->execute();
        $response['success'] = true;
        $response['message'] = "Utilizador '$nome' criado.";
        $stmt->close();
    } catch (mysqli_sql_exception $e) {
        $response['message'] = $e->getMessage();
    }

// ── Alterar utilizador ────────────────────────────────────────────────────
} elseif ($action === 'edit') {
    $id_utilizador = (int)($_REQUEST['id_utilizador'] ?? 0);
    $nome          = $_REQUEST['nome']            ?? null;
    $email         = $_REQUEST['email']           ?? null;
    $tipo          = $_REQUEST['tipo']            ?? null;
    $id_team       = $_REQUEST['id_team']         ?? null;
    $telemovel     = $_REQUEST['telemovel']       ?? null;
    $data_nasc     = $_REQUEST['data_nascimento'] ?? null;

    if ($id_utilizador <= 0) {
        $response['message'] = 'ID de utilizador inválido.';
        echo json_encode($response);
        exit;
    }

    try {
        $id_team   = $id_team   ? (int)$id_team : null;
        $data_nasc = $data_nasc ?: null;

        $stmt = $conn->prepare("CALL SP_AlterarUtilizador(?, ?, ?, ?, ?, ?, ?)");
        $stmt->bind_param("issssss",
            $id_utilizador, $nome, $email, $tipo,
            $id_team, $telemovel, $data_nasc
        );
        $stmt->execute();
        $response['success'] = true;
        $response['message'] = 'Utilizador actualizado.';
        $stmt->close();
    } catch (mysqli_sql_exception $e) {
        $response['message'] = $e->getMessage();
    }

// ── Apagar utilizador ─────────────────────────────────────────────────────
} elseif ($action === 'delete') {
    $id_utilizador = (int)($_REQUEST['id_utilizador'] ?? 0);

    if ($id_utilizador <= 0) {
        $response['message'] = 'ID de utilizador inválido.';
        echo json_encode($response);
        exit;
    }

    try {
        $stmt = $conn->prepare("CALL SP_ApagarUtilizador(?)");
        $stmt->bind_param("i", $id_utilizador);
        $stmt->execute();
        $response['success'] = true;
        $response['message'] = 'Utilizador apagado.';
        $stmt->close();
    } catch (mysqli_sql_exception $e) {
        $response['message'] = $e->getMessage();
    }

} else {
    $response['message'] = 'Ação inválida. Use: list, create, edit, delete';
}

$conn->close();
echo json_encode($response);
?>