<?php
error_reporting(E_ALL);
ini_set('display_errors', 1);
header('Content-Type: application/json');

$response = array('success' => false, 'message' => '', 'data' => array());

$database = $_REQUEST['database'] ?? '';
if (empty($database)) {
    $response['message'] = 'Database em falta.';
    echo json_encode($response);
    exit;
}

$conn = new mysqli('localhost', 'root', 'admin', $database, 3307);
if ($conn->connect_error) {
    $response['message'] = "Erro de conexão: " . $conn->connect_error;
    echo json_encode($response);
    exit;
}

$sql = "SELECT ID AS id, alertType AS tipoalerta, writtenAt AS hora, 
               message AS msg, reading AS leitura, sensor 
        FROM Messages 
        WHERE ID_simulation = (SELECT ID FROM Simulation WHERE status = 'active' ORDER BY ID DESC LIMIT 1)
        ORDER BY ID DESC";
$result = $conn->query($sql);
if ($result) {
    $messages = array();
    while ($row = $result->fetch_assoc()) {
        $messages[] = $row;
    }
    $response['success'] = true;
    $response['data'] = $messages;
    $response['message'] = 'Mensagens carregadas com sucesso.';
} else {
    $response['message'] = 'Erro ao executar consulta: ' . $conn->error;
}
$conn->close();
echo json_encode($response);
?>