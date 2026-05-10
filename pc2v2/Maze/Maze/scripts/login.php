<?php
error_reporting(E_ALL);
ini_set('display_errors', 1);
header('Content-Type: application/json');

$response = array('success' => false, 'message' => '');

$username = $_REQUEST['username'] ?? '';
$password = $_REQUEST['password'] ?? '';
$database = $_REQUEST['database'] ?? '';

if (empty($username) || empty($password) || empty($database)) {
    $response['message'] = 'Preencha todos os campos.';
    echo json_encode($response);
    exit;
}

$conn = new mysqli('localhost', 'root', 'admin', $database, 3307);

if ($conn->connect_error) {
    $response['message'] = "Erro de conexão: " . $conn->connect_error;
    echo json_encode($response);
    exit;
}

$sql = "SELECT team FROM User WHERE email = ? AND password = ?";
$stmt = $conn->prepare($sql);

if ($stmt) {
    $stmt->bind_param("ss", $username, $password);
    $stmt->execute();
    $result = $stmt->get_result();
    $user = $result->fetch_assoc();

    if ($user) {
        $response['success'] = true;
        $response['IDGrupo'] = $user['team'];
        $response['message'] = 'Login bem-sucedido.';
    } else {
        $response['message'] = 'Credenciais inválidas.';
    }
    $stmt->close();
} else {
    $response['message'] = 'Erro na query: ' . $conn->error;
}

$conn->close();
echo json_encode($response);
?>