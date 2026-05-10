<?php
error_reporting(E_ALL);
ini_set('display_errors', 1);
header('Content-Type: application/json');

$response = array('success' => false, 'message' => '', 'data' => null);

$username = $_REQUEST['username'] ?? '';
$password = $_REQUEST['password'] ?? '';
$database = $_REQUEST['database'] ?? '';

$conn = new mysqli('localhost', $username, $password, $database, 3307);

if ($conn->connect_error) {
    $response['message'] = "Erro de ligação: " . $conn->connect_error;
    echo json_encode($response);
    exit;
}

$sql = "SELECT tempLimit AS maximo FROM Simulation WHERE ID = 1 LIMIT 1";
$result = $conn->query($sql);

if ($result && $row = $result->fetch_assoc()) {
    $response['success'] = true;
    $response['data'] = array(
        "minimo" => 0.0,
        "maximo" => (float)$row['maximo']
    );
    $response['message'] = 'Limites de temperatura carregados.';
} else {
    $response['message'] = "Erro na query: " . $conn->error;
}

$conn->close();
echo json_encode($response);
?>