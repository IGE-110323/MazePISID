<?php
error_reporting(E_ALL);
ini_set('display_errors', 1);
header('Content-Type: application/json');

$response = array('success' => false, 'message' => '', 'data' => null);

$database = $_REQUEST['database'] ?? '';
if (empty($database)) {
    $response['message'] = 'Database em falta.';
    echo json_encode($response);
    exit;
}

$conn = new mysqli('localhost', 'root', 'admin', $database, 3307);
if ($conn->connect_error) {
    $response['message'] = "Erro de ligação: " . $conn->connect_error;
    echo json_encode($response);
    exit;
}

$sql = "SELECT COALESCE(tempLimit, 40) AS maximo FROM Simulation 
        WHERE status = 'active' ORDER BY ID DESC LIMIT 1";
$result = $conn->query($sql);
if ($result && $row = $result->fetch_assoc()) {
    $response['success'] = true;
    $response['data'] = array(
        'minimo' => 0.0,
        'maximo' => (float)$row['maximo']
    );
    $response['message'] = 'Limites de temperatura carregados.';
} else {
    $response['message'] = "Erro na query: " . $conn->error;
}
$conn->close();
echo json_encode($response);
?>