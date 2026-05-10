<?php
error_reporting(E_ALL);
ini_set('display_errors', 1);
header('Content-Type: application/json');
header('Access-Control-Allow-Origin: *');

require_once 'db_config.php';

$response = array('success' => false, 'message' => '', 'data' => null);

$database     = $_REQUEST['database']      ?? '';
$action       = $_REQUEST['action']        ?? '';
$nome         = $_REQUEST['nome']          ?? '';
$player_number= (int)($_REQUEST['player_number'] ?? 0);
$password     = $_REQUEST['password']      ?? '';

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

if ($action === 'list') {
    $result = $conn->query("SELECT IDTeam, Name, PlayerNumber FROM Team ORDER BY IDTeam DESC");
    $teams  = array();
    while ($row = $result->fetch_assoc()) $teams[] = $row;
    $response['success'] = true;
    $response['data']    = $teams;

} elseif ($action === 'create') {
    if (empty($nome) || empty($password) || $player_number <= 0) {
        $response['message'] = 'Nome, password e número de player são obrigatórios.';
        echo json_encode($response);
        exit;
    }
    $stmt = $conn->prepare("INSERT INTO Team (Name, PasswordHash, PlayerNumber) VALUES (?, SHA2(?, 256), ?)");
    $stmt->bind_param("ssi", $nome, $password, $player_number);
    if ($stmt->execute()) {
        $response['success'] = true;
        $response['data']    = array('IDTeam' => $conn->insert_id);
        $response['message'] = "Equipa '$nome' criada.";
    } else {
        $response['message'] = 'Erro ao criar equipa: ' . $conn->error;
    }
    $stmt->close();

} else {
    $response['message'] = 'Ação inválida. Use: list, create';
}

$conn->close();
echo json_encode($response);
?>