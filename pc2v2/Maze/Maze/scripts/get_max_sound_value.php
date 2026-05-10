<?php
error_reporting(E_ALL);
ini_set('display_errors', 1);
header('Content-Type: application/json');

$response = array('success' => false, 'message' => '', 'data' => null);

$username = $_REQUEST['username'] ?? '';
$password = $_REQUEST['password'] ?? '';
$database = $_REQUEST['database'] ?? '';

if (empty($username) || empty($password) || empty($database)) {
    $response['message'] = 'Preencha todos os campos.';
    echo json_encode($response);
    exit;
}

$conn = new mysqli('localhost', $username, $password, $database, 3307);

if ($conn->connect_error) {
    $response['message'] = "Erro de conexão: " . $conn->connect_error;
    echo json_encode($response);
    exit;
}

$sql = "SELECT soundLimit AS maximo FROM Simulation WHERE ID = 1 LIMIT 1";
$result = $conn->query($sql);

if ($result && $row = $result->fetch_assoc()) {
    $response['success'] = true;
    $response['data'] = $row;
    $response['message'] = 'Configuração de som carregada.';
} else {
    $response['message'] = "Erro na query: " . $conn->error;
}

$conn->close();
echo json_encode($response);
?>