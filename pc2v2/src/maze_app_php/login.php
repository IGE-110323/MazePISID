<?php
error_reporting(E_ALL);
ini_set('display_errors', 1);
header('Content-Type: application/json');
header('Access-Control-Allow-Origin: *');

require_once 'db_config.php';

$response = array('success' => false, 'message' => '');

$username = $_REQUEST['username'] ?? '';
$password = $_REQUEST['password'] ?? '';
$database = $_REQUEST['database'] ?? '';

if (empty($username) || empty($password) || empty($database)) {
    $response['message'] = 'Preencha todos os campos.';
    echo json_encode($response);
    exit;
}

$conn = new mysqli(DB_HOST, DB_USER_ANDROID, DB_PASS_ANDROID, $database);

if ($conn->connect_error) {
    $response['message'] = "Erro de conexão MySQL: " . $conn->connect_error;
    echo json_encode($response);
    exit;
}

// Só permite login a utilizadores ADM
$sql = "SELECT IDUtilizador, IDTeam AS equipa, Nome, Tipo 
        FROM Utilizador 
        WHERE Email = ? 
          AND PasswordHash = SHA2(?, 256)
          AND Tipo = 'ADM'
          AND DeletedAt IS NULL";
$stmt = $conn->prepare($sql);

if ($stmt) {
    $stmt->bind_param("ss", $username, $password);
    $stmt->execute();
    $result = $stmt->get_result();
    $user   = $result->fetch_assoc();

    if ($user) {
        $response['success']      = true;
        $response['IDGrupo']      = $user['equipa'];
        $response['IDUtilizador'] = $user['IDUtilizador'];
        $response['Nome']         = $user['Nome'];
        $response['Tipo']         = $user['Tipo'];
        $response['message']      = 'Login bem-sucedido.';
    } else {
        // Mensagem genérica — não revela se o email existe ou se é USR
        $response['message'] = 'Credenciais inválidas ou sem permissão de acesso.';
    }
    $stmt->close();
} else {
    $response['message'] = 'Erro na preparação da query: ' . $conn->error;
}

$conn->close();
echo json_encode($response);
?>